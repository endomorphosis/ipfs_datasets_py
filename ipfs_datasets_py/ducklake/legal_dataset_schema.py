"""Schema and request route for every published legal dataset.

The inventory is the Hugging Face ids under ``justicedao`` and
``endomorphosis``. Classification is by repository name. This module does
not download parquet, and the catalog tables do not store document bodies
or embedding floats.

``request_legal_data`` is the single research-only request. It returns the
datasets whose schema matches the request. A request can name the
instrument (caselaw, statute, court, regulation, rule of procedure), the
nested level (national, state, municipal), and a GPS point. The point
resolves through the US county polygons and the municipal seed. When a
legal-search catalog has BM25 ranges, topic words also return posting
routes. Official sources stay the authority. The result does not contain
document text.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from ipfs_datasets_py.ducklake.legal_search_catalog import (
    Bm25Route,
    LegalSearchCatalogError,
    ensure_legal_dataset_tables,
    route_bm25_terms,
)
from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    fold_alias,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    CorpusRelease,
    _SLUG_ALIAS,
    build_release_registry,
)

_INVENTORY = (
    Path(__file__).resolve().parents[1]
    / "processors"
    / "legal_data"
    / "legal_dataset_inventory.txt"
)
_LAYOUT_ORDER = {
    "caselaw-graphrag/v1": 0,
    "country-laws-ir-graphrag/v1": 0,
    "publicus-ir-graphrag/v2": 0,
    "patent-legal-ir-graphrag": 0,
    "caselaw-text": 1,
    "caselaw-embeddings": 1,
    "municipal-gnis": 1,
    "world-law/v1.1.0": 2,
    "legal-record/v1": 2,
    "legacy-split": 3,
    "unverified": 4,
    "excluded": 5,
    "unclassified": 6,
}
_IR_FIELDS = (
    ("corpus", "entry_cid", "varchar", "key"),
    ("corpus", "document_index", "integer", "locator"),
    ("corpus", "title", "varchar", "attribute"),
    ("corpus", "record_type", "varchar", "attribute"),
    ("corpus", "text", "varchar", "document"),
    ("bm25_keyword_index", "first_key", "varchar", "routing"),
    ("bm25_keyword_index", "last_key", "varchar", "routing"),
    ("bm25_keyword_index", "shard_id", "integer", "locator"),
    ("bm25_keyword_index", "sha256", "varchar", "locator"),
    ("bm25_keyword_index", "row_count", "integer", "locator"),
    ("vectors", "entry_cid", "varchar", "key"),
    ("vectors", "embedding", "fixed_size_list_float32", "vector"),
    ("graph_nodes", "node_cid", "varchar", "key"),
    ("graph_edges", "source_cid", "varchar", "key"),
    ("graph_edges", "target_cid", "varchar", "locator"),
    ("graph_edges", "relation", "varchar", "attribute"),
)
_LAYOUT_FIELDS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "country-laws-ir-graphrag/v1": _IR_FIELDS,
    "publicus-ir-graphrag/v2": _IR_FIELDS,
    "patent-legal-ir-graphrag": _IR_FIELDS,
    "caselaw-graphrag/v1": (
        ("corpus", "law_id", "varchar", "key"),
        ("corpus", "entry_cid", "varchar", "locator"),
        ("corpus", "document_index", "integer", "locator"),
        ("corpus", "title", "varchar", "attribute"),
        ("corpus", "jurisdiction", "varchar", "attribute"),
        ("corpus", "court", "varchar", "attribute"),
        ("corpus", "decision_date", "varchar", "attribute"),
        ("corpus", "body", "varchar", "document"),
        ("chunks", "entry_cid", "varchar", "key"),
        ("chunks", "law_id", "varchar", "locator"),
        ("chunks", "document_index", "integer", "locator"),
        ("vectors", "entry_cid", "varchar", "key"),
        ("vectors", "cluster_id", "integer", "locator"),
        ("vectors", "embedding", "fixed_size_list_float32", "vector"),
        ("graph_nodes", "node_cid", "varchar", "key"),
        ("graph_edges", "source_cid", "varchar", "key"),
        ("graph_edges", "target_cid", "varchar", "locator"),
        ("graph_edges", "relation", "varchar", "attribute"),
    ),
    "caselaw-text": (
        ("corpus", "id", "varchar", "key"),
        ("corpus", "text", "varchar", "document"),
    ),
    "caselaw-embeddings": (
        ("vectors", "cid", "varchar", "key"),
        ("vectors", "embedding", "fixed_size_list_float32", "vector"),
    ),
    "legal-record/v1": (
        ("record", "entry_cid", "varchar", "key"),
        ("record", "jurisdiction", "varchar", "attribute"),
        ("record", "citation", "varchar", "attribute"),
        ("record", "title", "varchar", "attribute"),
        ("record", "language", "varchar", "attribute"),
        ("record", "text", "varchar", "document"),
    ),
    "world-law/v1.1.0": (
        ("record", "entry_cid", "varchar", "key"),
        ("record", "jurisdiction", "varchar", "attribute"),
        ("record", "title", "varchar", "attribute"),
        ("record", "text", "varchar", "document"),
    ),
    "legacy-split": (
        ("corpus", "cid", "varchar", "key"),
        ("corpus", "text", "varchar", "document"),
    ),
    "municipal-gnis": (("corpus", "cid", "varchar", "key"),),
    "unverified": (("corpus", "entry_cid", "varchar", "key"),),
}


@dataclass(frozen=True)
class LayoutField:
    """One remote field. The catalog stores the name, not the field's values."""

    layout_profile: str
    family: str
    field_name: str
    logical_type: str
    field_role: str


@dataclass(frozen=True)
class DatasetSchema:
    """One published dataset the request interface can name."""

    hf_repo: str
    corpus_id: str
    layout_profile: str
    coverage: str
    primary_key_field: str
    instrument_kind: str
    selected: bool
    searchable: bool
    text_corpus: bool
    fields: tuple[LayoutField, ...] = ()
    siblings: tuple[str, ...] = ()
    research_only: bool = True
    authoritative: bool = False
    ducklake_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative or self.ducklake_authoritative or not self.research_only:
            raise LegalSearchCatalogError("search pin must stay observational")


@dataclass(frozen=True)
class ApplicablePlace:
    """Governments that contain a coordinate or a named US place.

    ``status`` is ``one`` for a county polygon, ``named`` for a state or
    city without a coordinate, and ``none``, ``ambiguous``, or ``unindexed``
    when the point cannot be placed. Coordinates outside the US county
    index are ``none``.
    """

    status: str
    latitude: str = ""
    longitude: str = ""
    country_code: str | None = None
    state_code: str | None = None
    county_name: str | None = None
    municipal_name: str | None = None


@dataclass(frozen=True)
class LawLayer:
    """Datasets that apply at one level of government."""

    admin_level: str
    jurisdiction_code: str
    place_name: str | None
    datasets: tuple[DatasetSchema, ...]


@dataclass(frozen=True)
class LegalDataResult:
    """Datasets and optional BM25 routes for one legal-data request."""

    datasets: tuple[DatasetSchema, ...]
    routes: tuple[Bm25Route, ...] = ()
    place: ApplicablePlace | None = None
    layers: tuple[LawLayer, ...] = ()
    topic: str | None = None
    research_only: bool = True
    authoritative: bool = False
    ducklake_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative or self.ducklake_authoritative or not self.research_only:
            raise LegalSearchCatalogError("search pin must stay observational")


def _fields_for(layout_profile: str) -> tuple[LayoutField, ...]:
    rows = _LAYOUT_FIELDS.get(layout_profile, ())
    return tuple(
        LayoutField(layout_profile, family, name, logical_type, role)
        for family, name, logical_type, role in rows
    )


def _schema_from_release(
    release: CorpusRelease,
    siblings: tuple[str, ...] = (),
) -> DatasetSchema:
    return DatasetSchema(
        hf_repo=release.hf_repo,
        corpus_id=release.corpus_id,
        layout_profile=release.layout_profile,
        coverage=release.coverage,
        primary_key_field=release.primary_key,
        instrument_kind=release.instrument_kind,
        selected=release.selected,
        searchable=release.searchable,
        text_corpus=release.text_corpus,
        fields=_fields_for(release.layout_profile),
        siblings=siblings,
        research_only=release.research_only,
        authoritative=release.authoritative,
        ducklake_authoritative=release.ducklake_authoritative,
    )


@lru_cache(maxsize=1)
def published_dataset_ids() -> tuple[str, ...]:
    """Dataset ids captured from the two Hugging Face orgs."""

    if not _INVENTORY.is_file():
        raise LegalSearchCatalogError("legal dataset inventory is missing")
    ids: list[str] = []
    seen: set[str] = set()
    for raw in _INVENTORY.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            raise LegalSearchCatalogError(f"duplicate dataset id: {line}")
        seen.add(line)
        ids.append(line)
    if not ids:
        raise LegalSearchCatalogError("legal dataset inventory is empty")
    return tuple(ids)


def legal_dataset_schema(
    dataset_ids: Iterable[str] | None = None,
) -> tuple[CorpusRelease, ...]:
    """Classify dataset ids. The default is the published inventory."""

    ids = published_dataset_ids() if dataset_ids is None else tuple(dataset_ids)
    return build_release_registry(ids)


def _require_observational(release: CorpusRelease) -> None:
    if release.authoritative or release.ducklake_authoritative or not release.research_only:
        raise LegalSearchCatalogError("search pin must stay observational")


def maintain_legal_dataset_schema(
    connection,
    releases: Sequence[CorpusRelease] | None = None,
) -> dict[str, int]:
    """Replace the catalog's dataset schema with *releases*.

    Passing no releases stores the published inventory. Rows name repos and
    field names. They do not copy document text or vectors into the catalog.
    """

    ensure_legal_dataset_tables(connection)
    chosen = tuple(legal_dataset_schema() if releases is None else releases)
    for release in chosen:
        _require_observational(release)
    connection.execute("DELETE FROM legal_dataset")
    connection.execute("DELETE FROM legal_dataset_field")
    if chosen:
        connection.executemany(
            """
            INSERT INTO legal_dataset VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, FALSE, FALSE)
            """,
            [
                (
                    release.hf_repo,
                    release.corpus_id,
                    release.layout_profile,
                    release.coverage,
                    release.primary_key,
                    release.instrument_kind,
                    release.selected,
                    release.searchable,
                    release.text_corpus,
                )
                for release in chosen
            ],
        )
    field_rows: list[tuple[str, str, str, str, str]] = []
    seen_fields: set[tuple[str, str, str]] = set()
    for layout in {release.layout_profile for release in chosen}:
        for field in _fields_for(layout):
            key = (field.layout_profile, field.family, field.field_name)
            if key in seen_fields:
                continue
            seen_fields.add(key)
            field_rows.append(key + (field.logical_type, field.field_role))
    if field_rows:
        connection.executemany(
            "INSERT INTO legal_dataset_field VALUES (?, ?, ?, ?, ?)",
            field_rows,
        )
    return {"datasets": len(chosen), "fields": len(field_rows)}


def _load_stored_schema(connection) -> tuple[DatasetSchema, ...]:
    ensure_legal_dataset_tables(connection)
    count = connection.execute("SELECT COUNT(*) FROM legal_dataset").fetchone()
    if count is None or int(count[0]) == 0:
        maintain_legal_dataset_schema(connection)
    dataset_rows = connection.execute(
        """
        SELECT hf_repo, corpus_id, layout_profile, coverage, primary_key_field,
               instrument_kind, selected, searchable, text_corpus,
               research_only, authoritative, ducklake_authoritative
        FROM legal_dataset
        ORDER BY corpus_id, hf_repo
        """
    ).fetchall()
    field_rows = connection.execute(
        """
        SELECT layout_profile, family, field_name, logical_type, field_role
        FROM legal_dataset_field
        ORDER BY layout_profile, family, field_name
        """
    ).fetchall()
    by_layout: dict[str, list[LayoutField]] = {}
    for layout, family, name, logical_type, role in field_rows:
        by_layout.setdefault(str(layout), []).append(
            LayoutField(str(layout), str(family), str(name), str(logical_type), str(role))
        )
    grouped: dict[str, list[str]] = {}
    pending: list[tuple] = []
    for row in dataset_rows:
        if bool(row[10]) or bool(row[11]) or not bool(row[9]):
            raise LegalSearchCatalogError("stored legal dataset claims authority")
        grouped.setdefault(str(row[1]), []).append(str(row[0]))
        pending.append(row)
    schemas: list[DatasetSchema] = []
    for row in pending:
        repo = str(row[0])
        corpus_id = str(row[1])
        siblings = tuple(sorted(item for item in grouped[corpus_id] if item != repo))
        schemas.append(
            DatasetSchema(
                hf_repo=repo,
                corpus_id=corpus_id,
                layout_profile=str(row[2]),
                coverage=str(row[3]),
                primary_key_field=str(row[4]),
                instrument_kind=str(row[5]),
                selected=bool(row[6]),
                searchable=bool(row[7]),
                text_corpus=bool(row[8]),
                fields=tuple(by_layout.get(str(row[2]), ())),
                siblings=siblings,
            )
        )
    return tuple(schemas)


def _memory_schema(releases: Sequence[CorpusRelease]) -> tuple[DatasetSchema, ...]:
    grouped: dict[str, list[str]] = {}
    for release in releases:
        grouped.setdefault(release.corpus_id, []).append(release.hf_repo)
    return tuple(
        _schema_from_release(
            release,
            tuple(
                sorted(
                    repo
                    for repo in grouped[release.corpus_id]
                    if repo != release.hf_repo
                )
            ),
        )
        for release in releases
    )


def _slug_match(corpus_id: str, slug: str) -> bool:
    token = slug.strip().casefold()
    if not token:
        return False
    if corpus_id in {f"country:{token}", f"world:{token}"}:
        return True
    return corpus_id.startswith(f"country:{token}:") or corpus_id.startswith(
        f"country:{token}_"
    )


_INSTRUMENTS = {
    "caselaw": "case",
    "case": "case",
    "cases": "case",
    "opinion": "case",
    "opinions": "case",
    "statute": "statute",
    "statutes": "statute",
    "statues": "statute",
    "law": "statute",
    "laws": "statute",
    "code": "statute",
    "ordinance": "ordinance",
    "ordinances": "ordinance",
    "court": "court",
    "courts": "court",
    "regulation": "regulation",
    "regulations": "regulation",
    "rule": "rule",
    "rules": "rule",
    "rules of procedure": "rule",
    "rule of procedure": "rule",
    "procedure": "rule",
    "court rules": "rule",
    "register": "register",
    "patent": "patent",
    "order": "order",
    "executive order": "order",
    "form": "form",
}
_LEVELS = {
    "national": "national",
    "country": "national",
    "federal": "national",
    "us-federal": "national",
    "state": "state",
    "province": "state",
    "regional": "state",
    "us-state": "state",
    "adm1": "state",
    "municipal": "municipal",
    "municipality": "municipal",
    "city": "municipal",
    "local": "municipal",
    "us-municipal": "municipal",
    "county": "county",
}
_NATIONAL_US = frozenset({
    "us:code",
    "us:cfr",
    "us:federal-register",
    "us:patent",
    "us:executive-orders",
    "us:open-us-law",
    "us:publicus",
})
_STATE_US = frozenset({
    "us:state-statutes",
    "us:state-statutes-normalized",
    "us:state-admin-rules",
    "us:court-rules",
})


def corpus_admin_level(corpus_id: str, instrument_kind: str = "") -> str:
    """Return national, state, municipal, or judicial for one corpus id."""

    if corpus_id.startswith("us:"):
        if corpus_id in _NATIONAL_US or corpus_id.startswith("us:federal"):
            return "national"
        if corpus_id in _STATE_US or corpus_id.startswith("us:state"):
            return "state"
        if "municipal" in corpus_id:
            return "municipal"
        if corpus_id.startswith("us:caselaw") or corpus_id == "us:courts":
            return "judicial"
        return "national"
    if corpus_id.startswith("country:"):
        rest = corpus_id[len("country:") :]
        if (
            instrument_kind == "ordinance"
            or "_municipal" in rest
            or rest.endswith("_local_acts")
        ):
            return "municipal"
        if "subnational" in rest:
            return "state"
        return "national"
    if "municipal" in corpus_id:
        return "municipal"
    return "national"


def _level_matches(corpus_id: str, instrument_kind: str, level: str | None) -> bool:
    if not level:
        return True
    found = corpus_admin_level(corpus_id, instrument_kind)
    if level == "national":
        return found in {"national", "judicial"}
    if level == "state":
        return found in {"state", "judicial"}
    if level == "municipal":
        return found == "municipal"
    if level == "county":
        return found == "municipal"
    return False


def _normalize_instrument(value: str | None) -> str:
    text = " ".join(str(value or "").strip().casefold().split())
    if not text:
        return ""
    kind = _INSTRUMENTS.get(text)
    if kind is None:
        raise LegalSearchCatalogError("instrument")
    return kind


def _normalize_level(value: str | None) -> str:
    text = " ".join(str(value or "").strip().casefold().split())
    if not text:
        return ""
    level = _LEVELS.get(text)
    if level is None:
        raise LegalSearchCatalogError("admin_level")
    return level


def _us_state_code(token: str, *, allow_code: bool) -> str | None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
        STATE_NAME,
    )

    text = token.strip()
    upper = text.upper()
    if allow_code and len(upper) == 2 and upper in STATE_NAME:
        return upper
    folded = text.casefold()
    for code, name in STATE_NAME.items():
        if name.casefold() == folded:
            return code
    return None


def _named_us_place(token: str) -> ApplicablePlace | None:
    """Resolve a US state name, ``US-NE``, or ``City, ST`` without a coordinate.

    A bare ISO code such as ``NE`` stays a country. It is not Nebraska.
    """

    state = _us_state_code(token, allow_code=False)
    if state is not None:
        return ApplicablePlace(
            status="named",
            country_code="US",
            state_code=state,
        )
    if "-" in token:
        parent, _, sub = token.partition("-")
        if parent.casefold() == "us":
            sub_state = _us_state_code(sub, allow_code=True)
            if sub_state is not None:
                return ApplicablePlace(
                    status="named",
                    country_code="US",
                    state_code=sub_state,
                )
    if "," not in token:
        return None
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceQueryError,
        resolve_municipal_place,
    )

    try:
        found = resolve_municipal_place(token, None, None)
    except PlaceQueryError as exc:
        raise LegalSearchCatalogError(str(exc)) from exc
    if found is None:
        return None
    return ApplicablePlace(
        status="named",
        country_code="US",
        state_code=found.state_code,
        municipal_name=found.name,
    )


def _coordinate_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise LegalSearchCatalogError(field)
    if isinstance(value, float):
        return format(value, "f").rstrip("0").rstrip(".")
    return str(value).strip()


def _resolve_gps(latitude: str, longitude: str) -> ApplicablePlace:
    from ipfs_datasets_py.processors.legal_data.county_geography import (
        locate_governments,
    )
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceQueryError,
        resolve_municipal_place,
    )

    governments = locate_governments(latitude, longitude)
    if governments.status != "one" or governments.county is None:
        return ApplicablePlace(
            status=governments.status,
            latitude=latitude,
            longitude=longitude,
        )
    county = governments.county
    municipal_name = None
    try:
        found = resolve_municipal_place(None, latitude, longitude)
    except PlaceQueryError as exc:
        raise LegalSearchCatalogError(str(exc)) from exc
    if found is not None and found.state_code == county.state_code:
        municipal_name = found.name
    return ApplicablePlace(
        status="one",
        latitude=latitude,
        longitude=longitude,
        country_code="US",
        state_code=county.state_code,
        county_name=county.name,
        municipal_name=municipal_name,
    )


_JURISDICTION_SUFFIXES = ("_municipal", "_local_acts", "_subnational")


def _canonical_jurisdiction_key(slug: str) -> str:
    """One matrix key for a country slug and its published aliases.

    ``dominican_republic`` and ``czech_municipal`` join the national slug.
    ``us`` and ``us_municipal`` join ``US``. A stem that does not resolve,
    such as ``spain_catalonia`` or ``us_local``, stays its own key.
    """

    text = str(slug or "").strip().casefold().replace("-", "_")
    if not text:
        return ""
    if text in {"us", "usa"}:
        return "US"
    resolved = resolve_jurisdiction(text)
    if resolved is not None and resolved.slug:
        return resolved.slug
    if (
        resolved is not None
        and resolved.code == "US"
        and resolved.admin_level == "country"
    ):
        return "US"
    stem = text
    for suffix in _JURISDICTION_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
            break
    aliased = fold_alias(_SLUG_ALIAS.get(stem, stem))
    if aliased in {"us", "usa"}:
        return "US"
    resolved_stem = resolve_jurisdiction(aliased)
    if resolved_stem is not None and resolved_stem.slug:
        return resolved_stem.slug
    if (
        resolved_stem is not None
        and resolved_stem.code == "US"
        and resolved_stem.admin_level == "country"
    ):
        return "US"
    return aliased


def _corpus_jurisdiction_key(corpus_id: str) -> str:
    if corpus_id.startswith("us:"):
        return "US"
    if corpus_id.startswith("world:"):
        return "world"
    if corpus_id.startswith("country:"):
        slug = corpus_id[len("country:") :].split(":", 1)[0]
        return _canonical_jurisdiction_key(slug)
    return ""


def _matches_jurisdiction(corpus_id: str, jurisdiction: str) -> bool:
    token = str(jurisdiction or "").strip()
    if not token:
        return True
    if token.casefold() in {"world", "international"}:
        return corpus_id.startswith("world:")
    resolved = resolve_jurisdiction(token)
    if resolved is not None and resolved.code == "US" and corpus_id.startswith("us:"):
        return True
    raw = token.replace("-", "_")
    if resolved is None or resolved.code != "US":
        if _slug_match(corpus_id, raw):
            return True
        if resolved is not None and resolved.slug and _slug_match(corpus_id, resolved.slug):
            return True
        if (
            resolved is not None
            and resolved.municipal_slug
            and _slug_match(corpus_id, resolved.municipal_slug)
        ):
            return True
    return _corpus_jurisdiction_key(corpus_id) == _canonical_jurisdiction_key(raw)


def _sort_key(item: DatasetSchema) -> tuple[int, int, str]:
    org_rank = 0 if item.hf_repo.startswith("justicedao/") else 1
    return (_LAYOUT_ORDER.get(item.layout_profile, 9), org_rank, item.hf_repo)


def _topic_terms(topic: str | None, terms: Iterable[str]) -> tuple[str, ...]:
    chosen: list[str] = []
    seen: set[str] = set()
    for raw in str(topic or "").split():
        token = raw.strip().casefold()
        if token and token not in seen:
            seen.add(token)
            chosen.append(token)
    for raw in terms:
        token = str(raw).strip()
        if token and token not in seen:
            seen.add(token)
            chosen.append(token)
    return tuple(chosen)


def _select_matches(
    stored: Sequence[DatasetSchema],
    *,
    requested_repo: str,
    requested_corpus: str,
    requested_jurisdiction: str,
    requested_kind: str,
    level: str,
    include_unselected: bool,
    text_only: bool,
) -> list[DatasetSchema]:
    explicit = bool(requested_repo)

    def keep(item: DatasetSchema, *, allow_unselected: bool) -> bool:
        if requested_repo and item.hf_repo != requested_repo:
            return False
        if requested_corpus and item.corpus_id != requested_corpus:
            return False
        if requested_jurisdiction and not _matches_jurisdiction(
            item.corpus_id, requested_jurisdiction
        ):
            return False
        if requested_kind and item.instrument_kind != requested_kind:
            return False
        if level and not _level_matches(item.corpus_id, item.instrument_kind, level):
            return False
        if not explicit and item.layout_profile == "excluded":
            return False
        if not explicit and text_only and not item.text_corpus:
            return False
        if explicit:
            return True
        if item.selected and item.searchable:
            return True
        return allow_unselected

    matched = [item for item in stored if keep(item, allow_unselected=include_unselected)]
    if matched or include_unselected or explicit:
        return matched
    if requested_kind or level:
        return [item for item in stored if keep(item, allow_unselected=True)]
    return []


def _build_layers(
    datasets: Sequence[DatasetSchema],
    place: ApplicablePlace | None,
    level: str,
) -> tuple[LawLayer, ...]:
    if place is None and not level:
        return ()
    grouped: dict[str, list[DatasetSchema]] = {
        "national": [],
        "state": [],
        "county": [],
        "municipal": [],
    }
    for item in datasets:
        found = corpus_admin_level(item.corpus_id, item.instrument_kind)
        if found == "judicial":
            grouped["national"].append(item)
            grouped["state"].append(item)
        elif found == "municipal":
            grouped["municipal"].append(item)
            grouped["county"].append(item)
        elif found in grouped:
            grouped[found].append(item)
    order = ("national", "state", "county", "municipal")
    if level:
        order = (level,)
    layers: list[LawLayer] = []
    country = place.country_code if place and place.country_code else ""
    state = place.state_code if place else None
    for name in order:
        rows = tuple(grouped[name])
        if not rows:
            continue
        code = country or "US" if state else country
        place_name = None
        if name == "state" and state:
            code = f"{country}-{state}" if country else state
            place_name = state
        elif name == "county" and place is not None:
            code = f"{country}-{state}" if country and state else code
            place_name = place.county_name
        elif name == "municipal" and place is not None:
            code = f"{country}-{state}" if country and state else code
            place_name = place.municipal_name
        elif name == "national" and country:
            code = country
        layers.append(
            LawLayer(
                admin_level=name,
                jurisdiction_code=code,
                place_name=place_name,
                datasets=rows,
            )
        )
    return tuple(layers)


def request_legal_data(
    *,
    jurisdiction: str | None = None,
    corpus_id: str | None = None,
    hf_repo: str | None = None,
    instrument_kind: str | None = None,
    admin_level: str | None = None,
    latitude: str | float | None = None,
    longitude: str | float | None = None,
    topic: str | None = None,
    terms: Iterable[str] = (),
    include_unselected: bool = False,
    text_only: bool = True,
    connection=None,
    releases: Sequence[CorpusRelease] | None = None,
) -> LegalDataResult:
    """Return the datasets that can answer one legal-data request.

    ``instrument_kind`` accepts caselaw, statute, court, regulation, and
    rule of procedure, plus the stored kind names. ``admin_level`` accepts
    national, state, county, and municipal. A latitude and longitude in the
    US county index select the national, state, county, and municipal
    datasets that apply at that point. ``topic`` is matched as BM25 terms
    when a catalog connection has posting ranges.

    The result names repositories, layout fields, and shard routes. It does
    not read or return document bodies. A catalog connection is loaded from
    the published inventory when its schema table is empty.
    """

    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceQueryError,
        parse_coordinates,
    )

    requested_kind = _normalize_instrument(instrument_kind)
    level = _normalize_level(admin_level)
    lat_text = _coordinate_text(latitude, "latitude")
    lon_text = _coordinate_text(longitude, "longitude")
    try:
        lat_text, lon_text = parse_coordinates(lat_text, lon_text)
    except PlaceQueryError as exc:
        raise LegalSearchCatalogError(str(exc)) from exc
    term_list = _topic_terms(topic, terms)
    topic_text = " ".join(str(topic).split()) if topic and str(topic).strip() else None
    requested_repo = str(hf_repo or "").strip()
    requested_corpus = str(corpus_id or "").strip()
    requested_jurisdiction = str(jurisdiction or "").strip()
    named_place = _named_us_place(requested_jurisdiction) if requested_jurisdiction else None
    gps_place = _resolve_gps(lat_text, lon_text) if lat_text and lon_text else None
    place = gps_place or named_place
    if (
        gps_place is not None
        and gps_place.country_code
        and named_place is not None
        and (
            named_place.country_code != gps_place.country_code
            or (
                named_place.state_code
                and gps_place.state_code
                and named_place.state_code != gps_place.state_code
            )
        )
    ):
        raise LegalSearchCatalogError("place_jurisdiction_mismatch")
    if gps_place is not None and gps_place.country_code and not named_place:
        resolved = resolve_jurisdiction(requested_jurisdiction) if requested_jurisdiction else None
        if resolved is not None and resolved.code != gps_place.country_code:
            raise LegalSearchCatalogError("place_jurisdiction_mismatch")
    if place is not None and place.country_code == "US":
        requested_jurisdiction = "US"
    if not any(
        (
            requested_jurisdiction,
            requested_corpus,
            requested_repo,
            requested_kind,
            level,
            term_list,
            gps_place is not None,
        )
    ):
        raise LegalSearchCatalogError(
            "a legal data request needs a jurisdiction, corpus, instrument, dataset, place, or terms"
        )
    located = gps_place is not None and gps_place.status == "one"
    if gps_place is not None and not located:
        return LegalDataResult(datasets=(), place=gps_place, topic=topic_text)
    if term_list and connection is None and not any(
        (
            requested_jurisdiction,
            requested_corpus,
            requested_repo,
            requested_kind,
            level,
            located,
        )
    ):
        raise LegalSearchCatalogError("terms need a legal search catalog")
    if requested_repo:
        org, name = requested_repo.split("/", 1) if "/" in requested_repo else ("justicedao", requested_repo)
        if org not in {"justicedao", "endomorphosis"} or not name:
            raise LegalSearchCatalogError(f"not a legal dataset id: {requested_repo!r}")
        requested_repo = f"{org}/{name}"

    if connection is not None:
        if releases is not None:
            maintain_legal_dataset_schema(connection, releases)
        stored = _load_stored_schema(connection)
    else:
        stored = _memory_schema(
            legal_dataset_schema() if releases is None else tuple(releases)
        )

    explicit = bool(requested_repo)
    matched = _select_matches(
        stored,
        requested_repo=requested_repo,
        requested_corpus=requested_corpus,
        requested_jurisdiction=requested_jurisdiction,
        requested_kind=requested_kind,
        level=level,
        include_unselected=include_unselected,
        text_only=text_only,
    )
    matched.sort(key=_sort_key)

    routes: tuple[Bm25Route, ...] = ()
    terms_only = not any(
        (
            requested_jurisdiction,
            requested_corpus,
            requested_repo,
            requested_kind,
            level,
            located,
        )
    )
    searchable_explicit = bool(matched) and matched[0].searchable
    if term_list and connection is not None and (not explicit or searchable_explicit):
        found = route_bm25_terms(connection, term_list)
        if terms_only:
            keep = {route.corpus_id for route in found}
            matched = [item for item in matched if item.corpus_id in keep]
            routes = tuple(route for route in found if route.corpus_id in keep)
        else:
            known = {item.corpus_id for item in matched}
            routes = tuple(route for route in found if route.corpus_id in known)
    report_place = gps_place or (named_place if named_place and named_place.state_code else None)
    return LegalDataResult(
        datasets=tuple(matched),
        routes=routes,
        place=report_place,
        layers=_build_layers(matched, report_place, level),
        topic=topic_text,
    )
