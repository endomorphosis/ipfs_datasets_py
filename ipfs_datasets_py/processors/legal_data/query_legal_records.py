"""Worldwide legal query. One schema, one jurisdiction, no US fallback.

``LEGAL_QUERY_NORMALIZED`` defaults on. Set it to ``0`` to stop before
jurisdiction resolution. This module does not download a corpus. A caller
may pass ``corpus_opener`` to hydrate rows after the pin is chosen. World
and norm repos are opened only when ``pin_readable`` is true.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Mapping

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    ResolvedJurisdiction,
    fold_alias,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_pins import (
    pin_readable,
    pin_revision,
)

_FLAG = "LEGAL_QUERY_NORMALIZED"
_RECORD_SCHEMA = "legal-record/v1"
_QUERY_SCHEMA = "legal-query/v1"
_CURRENT_BUNDLE = frozenset({
    "ipfs_uscode",
    "ipfs_state_laws",
    "federal-register-full-graphrag-v20260810",
    "patent-legal-ir-graphrag",
})
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_QUERY_ID_FIELDS = (
    "jurisdiction",
    "text_query",
    "citation",
    "instrument_type",
    "admin_level",
    "language",
    "limit",
    "allow_stale",
    "gap_status",
    "alias_revisions",
)
# Structural locators are hashed only when the caller sets one, so an
# ordinary request keeps the query id it had before these filters existed.
_LOCATOR_QUERY_FIELDS = ("title", "chapter", "section", "subsection")
# Place and date are hashed only when the caller sets them, same as locators.
_PLACE_QUERY_FIELDS = ("place", "latitude", "longitude", "as_of")
# Retrieval is hashed only when the caller asks for keyword or vector search.
_SEARCH_QUERY_FIELDS = ("retrieval",)


class LegalQueryDisabled(RuntimeError):
    """Raised when LEGAL_QUERY_NORMALIZED is set to a value other than ``1``."""


class LegalQueryInputError(ValueError):
    """Raised for a known jurisdiction whose request cannot be routed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NormalizedLegalRecord:
    record: dict[str, object]


@dataclass(frozen=True)
class LegalQueryResult:
    schema_version: str
    record_schema: str
    jurisdiction: str
    coverage: str
    source_repo: str | None
    source_revision: str | None
    records: tuple[dict[str, object], ...]
    query_id: str
    place_name: str | None = None
    place_state: str | None = None
    place_latitude: str | None = None
    place_longitude: str | None = None
    place_ambiguous: bool = False
    county_name: str | None = None
    county_state: str | None = None
    county_records: tuple[dict[str, object], ...] = ()
    territory_name: str | None = None
    territory_state: str | None = None
    territory_records: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class _Route:
    jurisdiction: str
    coverage: str
    source_repo: str | None
    source_revision: str | None
    open_repo: str | None


def query_legal_records(
    *,
    jurisdiction: str,
    text_query: str | None = None,
    citation: str | None = None,
    instrument_type: str | None = None,
    admin_level: str | None = None,
    language: str | None = None,
    limit: int = 20,
    allow_stale: bool = False,
    gap_status: str | None = None,
    alias_revisions: Mapping[str, tuple[str | None, str | None]] | None = None,
    representation: str = "record",
    corpus_opener: Callable[[str], tuple[dict[str, object], ...]] | None = None,
    title: str | None = None,
    chapter: str | None = None,
    section: str | None = None,
    subsection: str | None = None,
    place: str | None = None,
    latitude: str | None = None,
    longitude: str | None = None,
    as_of: str | None = None,
    retrieval: str | None = None,
) -> LegalQueryResult:
    """Return legal-record/v1 rows for one jurisdiction.

    ``language`` is accepted and reserved for the corpus reader. ``limit``
    is clamped to 1..100 and applies to source rows before a ``jsonld`` or
    ``text`` view expands a multi-unit row. ``representation`` is ``record``,
    ``jsonld``, or ``text``. It is not part of ``query_id``. The default
    ``record`` view returns the opener rows unchanged.

    ``title``, ``chapter``, ``section``, and ``subsection`` select atomic
    units by the locator stored in provenance. ``title`` is the title number,
    not the instrument name. Any one of them is enough to form a query.
    A set locator expands the opener rows first and then applies ``limit``
    to the matches. JSON-LD puts those locators in ``additionalProperty``.
    Omitted locators leave ``query_id`` unchanged.

    ``place`` is a municipality name. ``latitude`` and ``longitude`` are
    decimal-degree strings for that same place, not the caller's location.
    On the US municipal route they resolve through the primary GNIS seed.
    A name that matches several cities needs a state suffix or a coordinate
    within 25 km of one of those cities. ``as_of`` is ``YYYY-MM-DD`` and
    keeps rows whose ``effective_date`` is on or before that day. A row
    with no effective date does not match. This is not a repeal check.

    ``retrieval`` is ``keyword`` or ``vector``. It is omitted from
    ``query_id`` when unset. Keyword search keeps rows whose text or
    citation contains every query token. Vector search ranks that same
    section by a query-normalized integer inner product of binary
    token vectors. On the American municipal route, a missing ``corpus_opener``
    reads that place's rows from the local v4 tree and does not contact
    the Hub.

    A city is a subdivision of a county, so the result returns both
    sovereigns. Caller coordinates select the point. A city name uses
    that city's seed point. The county, parish, borough, or other county
    equivalent that contains the point is named, and the territory when
    the point is in one. ``records`` stay the city. ``county_records``
    and ``territory_records`` are the other governments' ordinances, each
    capped by ``limit``. The same stored authority is not copied into a
    second layer. A tied city coordinate does not pick a city.
    Connecticut planning regions are not treated as counties. A named
    county with no city point stays in ``records``.
    """

    if os.environ.get(_FLAG, "1") != "1":
        raise LegalQueryDisabled(
            "LEGAL_QUERY_NORMALIZED must be 1 before a jurisdiction is resolved"
        )
    if limit < 1 or limit > 100:
        raise LegalQueryInputError("limit_out_of_range")
    if representation not in {"record", "jsonld", "text"}:
        raise LegalQueryInputError("representation")
    locators = _locator_request(
        title=title,
        chapter=chapter,
        section=section,
        subsection=subsection,
    )
    place_text = _optional_text(place, "place")
    latitude_text, longitude_text = _coordinate_request(latitude, longitude)
    as_of_text = _as_of_request(as_of)
    retrieval_text = _retrieval_request(retrieval)
    query_id = _stable_query_id(
        jurisdiction=jurisdiction,
        text_query=text_query,
        citation=citation,
        instrument_type=instrument_type,
        admin_level=admin_level,
        language=language,
        limit=limit,
        allow_stale=allow_stale,
        gap_status=gap_status,
        alias_revisions=alias_revisions,
        title=locators.get("title"),
        chapter=locators.get("chapter"),
        section=locators.get("section"),
        subsection=locators.get("subsection"),
        place=place_text,
        latitude=latitude_text,
        longitude=longitude_text,
        as_of=as_of_text,
        retrieval=retrieval_text,
    )
    del language  # reader-side filter; resolving it here would change the flag order

    resolved = resolve_jurisdiction(jurisdiction)
    if resolved is None:
        return _result(
            jurisdiction=_echo_unknown(jurisdiction),
            coverage="not_published",
            source_repo=None,
            source_revision=None,
            records=(),
            query_id=query_id,
        )

    has_place = bool(place_text or latitude_text)
    has_selector = bool(locators or has_place or as_of_text or retrieval_text)
    _require_query_shape(
        resolved,
        text_query=text_query,
        citation=citation,
        instrument_type=instrument_type,
        admin_level=admin_level,
        has_place=has_place,
        has_selector=has_selector,
    )
    if retrieval_text and not (text_query or "").strip():
        raise LegalQueryInputError("text_query")
    route = _route(
        resolved,
        instrument_type=instrument_type,
        admin_level=_routed_admin_level(
            resolved,
            admin_level=admin_level,
            instrument_type=instrument_type,
            has_place=has_place,
        ),
        allow_stale=allow_stale,
        gap_status=gap_status,
        alias_revisions=alias_revisions,
    )
    records: tuple[dict[str, object], ...] = ()
    county_name: str | None = None
    county_state: str | None = None
    county_records: tuple[dict[str, object], ...] = ()
    territory_name: str | None = None
    territory_state: str | None = None
    territory_records: tuple[dict[str, object], ...] = ()
    place_ambiguous = False
    place_fields = _empty_place_fields()
    if route.open_repo is not None:
        city_error: LegalQueryInputError | None = None
        try:
            constraint = _place_constraint(
                route,
                place_text=place_text,
                latitude_text=latitude_text,
                longitude_text=longitude_text,
            )
        except LegalQueryInputError as exc:
            if exc.code != "ambiguous_place" or not latitude_text:
                raise
            city_error = exc
            constraint = None
            place_ambiguous = True
        if constraint is not None:
            place_fields = {
                "place_name": constraint.name,
                "place_state": constraint.state_code,
                "place_latitude": constraint.latitude,
                "place_longitude": constraint.longitude,
            }
        missed = _coordinates_missed(
            route,
            latitude_text=latitude_text,
            constraint=constraint,
        )
        point_lat, point_lon = _government_point(
            latitude_text,
            longitude_text,
            constraint,
        )
        governments = _governments_at(route, point_lat, point_lon)
        if city_error is not None and governments.status != "one":
            raise city_error
        opened: tuple[dict[str, object], ...] = ()
        if not missed:
            if corpus_opener is not None:
                opened = tuple(corpus_opener(route.open_repo))
            elif retrieval_text and route.open_repo == "justicedao/american_municipal_law_norm":
                opened = _open_municipal_section(constraint)
            if opened or retrieval_text:
                records = _select_records(
                    opened,
                    limit=limit,
                    locators=locators,
                    constraint=constraint,
                    as_of=as_of_text,
                    text_query=text_query,
                    retrieval=retrieval_text,
                )
        if governments.status == "one":
            city_fold = _city_fold(constraint)
            load_layers = bool(retrieval_text or corpus_opener is not None)
            county_name, county_state, county_records = _layer_records(
                governments.county,
                city_fold,
                opened=opened,
                limit=limit,
                locators=locators,
                as_of=as_of_text,
                text_query=text_query,
                retrieval=retrieval_text,
                load=load_layers,
            )
            taken = {city_fold, governments.county.authority_fold if governments.county else None}
            territory_name, territory_state, territory_records = _layer_records(
                governments.territory,
                taken,
                opened=opened,
                limit=limit,
                locators=locators,
                as_of=as_of_text,
                text_query=text_query,
                retrieval=retrieval_text,
                load=load_layers,
            )
    if route.coverage == "partial" and gap_status:
        records = tuple(_stamp_fallback(row, gap_status) for row in records)
    if representation != "record":
        records = _present(records, representation, locators)
        county_records = _present(county_records, representation, locators)
        territory_records = _present(territory_records, representation, locators)
    return _result(
        jurisdiction=route.jurisdiction,
        coverage=route.coverage,
        source_repo=route.source_repo,
        source_revision=route.source_revision,
        records=records,
        query_id=query_id,
        place_name=place_fields["place_name"],
        place_state=place_fields["place_state"],
        place_latitude=place_fields["place_latitude"],
        place_longitude=place_fields["place_longitude"],
        place_ambiguous=place_ambiguous,
        county_name=county_name,
        county_state=county_state,
        county_records=county_records,
        territory_name=territory_name,
        territory_state=territory_state,
        territory_records=territory_records,
    )


def _echo_unknown(raw: str) -> str:
    token = str(raw or "").strip()
    if len(token) == 2 and token.isalpha():
        return token.upper()
    return token


def _require_query_shape(
    resolved: ResolvedJurisdiction,
    *,
    text_query: str | None,
    citation: str | None,
    instrument_type: str | None,
    admin_level: str | None,
    has_place: bool,
    has_selector: bool,
) -> None:
    statute_like = instrument_type in {None, "", "statute"}
    if (
        resolved.code == "US"
        and resolved.admin_level != "adm1"
        and statute_like
        and not admin_level
        and not has_place
    ):
        raise LegalQueryInputError("admin_level_required")
    if not (text_query or "").strip() and not (citation or "").strip() and not has_selector:
        raise LegalQueryInputError("query_required")


def _routed_admin_level(
    resolved: ResolvedJurisdiction,
    *,
    admin_level: str | None,
    instrument_type: str | None,
    has_place: bool,
) -> str | None:
    """A US place or coordinate selects the municipal corpus.

    An explicit admin level is left as the caller set it. ``US-CA`` is an
    adm1 route and is not rewritten into a municipal query.
    """

    if admin_level or not has_place:
        return admin_level
    statute_like = instrument_type in {None, "", "statute"}
    if resolved.code == "US" and resolved.admin_level != "adm1" and statute_like:
        return "us-municipal"
    return admin_level


def _optional_text(value: object, code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LegalQueryInputError(code)
    stripped = value.strip()
    return stripped or None


def _coordinate_request(
    latitude: object,
    longitude: object,
) -> tuple[str | None, str | None]:
    if latitude is None and longitude is None:
        return None, None
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceQueryError,
        parse_coordinates,
    )

    try:
        return parse_coordinates(latitude, longitude)
    except PlaceQueryError as exc:
        raise LegalQueryInputError(exc.code) from exc


def _as_of_request(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LegalQueryInputError("as_of")
    from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
        calendar_date,
    )

    stripped = value.strip()
    if not stripped:
        return None
    parsed = calendar_date(stripped)
    if parsed is None:
        raise LegalQueryInputError("as_of")
    return parsed


def _empty_place_fields() -> dict[str, str | None]:
    return {
        "place_name": None,
        "place_state": None,
        "place_latitude": None,
        "place_longitude": None,
    }


def _us_municipal(route: _Route) -> bool:
    return route.open_repo in {
        "justicedao/american_municipal_law_norm",
        "justicedao/american_municipal_law",
    }


def _place_constraint(
    route: _Route,
    *,
    place_text: str | None,
    latitude_text: str | None,
    longitude_text: str | None,
) -> object:
    if not place_text and not latitude_text:
        return None
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceQueryError,
        authority_constraint,
        constraint_from_place,
        resolve_municipal_place,
    )

    if _us_municipal(route):
        try:
            found = resolve_municipal_place(place_text, latitude_text, longitude_text)
        except PlaceQueryError as exc:
            raise LegalQueryInputError(exc.code) from exc
        if found is not None:
            return constraint_from_place(found)
        if place_text and not latitude_text:
            return authority_constraint(place_text)
        return None
    if latitude_text:
        raise LegalQueryInputError("coordinates")
    if place_text:
        return authority_constraint(place_text)
    return None


def _coordinates_missed(
    route: _Route,
    *,
    latitude_text: str | None,
    constraint: object,
) -> bool:
    return bool(latitude_text) and constraint is None and _us_municipal(route)


def _route(
    resolved: ResolvedJurisdiction,
    *,
    instrument_type: str | None,
    admin_level: str | None,
    allow_stale: bool,
    gap_status: str | None,
    alias_revisions: Mapping[str, tuple[str | None, str | None]] | None,
) -> _Route:
    if resolved.admin_level == "adm1":
        return _closed(resolved.echo)
    if resolved.code == "US":
        return _route_us(
            instrument_type=instrument_type,
            admin_level=admin_level,
            allow_stale=allow_stale,
        )
    level = admin_level or resolved.admin_level
    if level == "municipality":
        return _route_municipal(resolved, allow_stale=allow_stale, gap_status=gap_status)
    return _route_national(
        resolved,
        allow_stale=allow_stale,
        gap_status=gap_status,
        alias_revisions=alias_revisions,
    )


def _route_us(*, instrument_type: str | None, admin_level: str | None, allow_stale: bool) -> _Route:
    if admin_level == "us-municipal" or instrument_type == "ordinance":
        if pin_readable("american_municipal_law_norm"):
            repo = "justicedao/american_municipal_law_norm"
            return _Route("US", "current", repo, pin_revision(repo), repo)
        if allow_stale:
            return _Route("US", "stale_pin", "justicedao/american_municipal_law", None, "justicedao/american_municipal_law")
        return _closed("US")
    repo = {
        "us-federal": "justicedao/ipfs_uscode",
        "us-state": "justicedao/ipfs_state_laws",
    }.get(admin_level or "")
    if repo is None and instrument_type == "register":
        repo = "justicedao/federal-register-full-graphrag-v20260810"
    elif repo is None and instrument_type == "case":
        repo = "justicedao/ipfs_caselaw_access_project"
    elif repo is None and instrument_type == "patent":
        repo = "justicedao/patent-legal-ir-graphrag"
    if repo is None:
        return _closed("US")
    name = repo.split("/", 1)[1]
    coverage = "current" if name in _CURRENT_BUNDLE else "snapshot"
    return _Route("US", coverage, repo, None, repo)


def _route_national(
    resolved: ResolvedJurisdiction,
    *,
    allow_stale: bool,
    gap_status: str | None,
    alias_revisions: Mapping[str, tuple[str | None, str | None]] | None,
) -> _Route:
    if not resolved.slug:
        return _closed(resolved.echo)
    slug = _select_alias_slug(resolved.slug, alias_revisions)
    if _excluded_national(slug):
        return _closed(resolved.echo)
    repo = f"justicedao/ipfs_{slug}_laws_ir"
    return _with_gap(
        echo=resolved.echo,
        ir_repo=repo,
        world_id="world_national_law",
        allow_stale=allow_stale,
        gap_status=gap_status,
    )


def _route_municipal(
    resolved: ResolvedJurisdiction,
    *,
    allow_stale: bool,
    gap_status: str | None,
) -> _Route:
    municipal = resolved.municipal_slug
    if not municipal:
        return _closed(resolved.echo)
    ir_repo = f"justicedao/ipfs_{municipal}_laws_ir"
    norm_id = f"ipfs_{municipal}_laws_norm"
    if gap_status in {None, "current", "stub_vectors"}:
        coverage = "stub_vectors" if gap_status == "stub_vectors" else "snapshot"
        if gap_status == "current":
            coverage = "current"
        return _Route(resolved.echo, coverage, ir_repo, None, ir_repo)
    if pin_readable(norm_id):
        repo = f"justicedao/{norm_id}"
        return _Route(resolved.echo, "partial", repo, pin_revision(norm_id), repo)
    return _with_gap(
        echo=resolved.echo,
        ir_repo=ir_repo,
        world_id="world_municipal_law",
        allow_stale=allow_stale,
        gap_status=gap_status,
    )


def _with_gap(
    *,
    echo: str,
    ir_repo: str,
    world_id: str,
    allow_stale: bool,
    gap_status: str | None,
) -> _Route:
    if gap_status in {None, "current"}:
        coverage = "current" if gap_status == "current" else "snapshot"
        return _Route(echo, coverage, ir_repo, None, ir_repo)
    if gap_status == "stub_vectors":
        return _Route(echo, "stub_vectors", ir_repo, None, ir_repo)
    if gap_status in {"stale", "missing", "incomplete"}:
        if pin_readable(world_id):
            repo = f"justicedao/{world_id}"
            return _Route(echo, "partial", repo, pin_revision(world_id), repo)
        if allow_stale and gap_status == "stale":
            return _Route(echo, "stale_pin", ir_repo, None, ir_repo)
        return _closed(echo)
    return _closed(echo)


def _locator_request(
    *,
    title: object,
    chapter: object,
    section: object,
    subsection: object,
) -> dict[str, str]:
    requested: dict[str, str] = {}
    for key, value in (
        ("title", title),
        ("chapter", chapter),
        ("section", section),
        ("subsection", subsection),
    ):
        if value is None:
            continue
        if not isinstance(value, str):
            raise LegalQueryInputError(key)
        stripped = value.strip()
        if stripped:
            requested[key] = stripped
    return requested


def _retrieval_request(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LegalQueryInputError("retrieval")
    stripped = value.strip().casefold()
    if not stripped:
        return None
    if stripped not in {"keyword", "vector"}:
        raise LegalQueryInputError("retrieval")
    return stripped


def _open_municipal_section(constraint: object) -> tuple[dict[str, object], ...]:
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceConstraint,
    )
    from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
        MunicipalSectionError,
        load_place_section,
    )

    if not isinstance(constraint, PlaceConstraint):
        return ()
    try:
        return load_place_section(constraint)
    except MunicipalSectionError as exc:
        raise LegalQueryInputError("corpus_unavailable") from exc


def _select_records(
    opened: tuple[dict[str, object], ...],
    *,
    limit: int,
    locators: Mapping[str, str],
    constraint: object,
    as_of: str | None,
    text_query: str | None = None,
    retrieval: str | None = None,
) -> tuple[dict[str, object], ...]:
    if not locators and constraint is None and as_of is None and not retrieval:
        return opened[:limit]
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceConstraint,
        place_matches,
    )
    from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
        expand_legal_record,
    )

    place_filter = constraint if isinstance(constraint, PlaceConstraint) else None
    matched: list[dict[str, object]] = []
    for row in opened:
        # Place and effective date live on the row. Reject those before
        # expanding ordinance text, which is the expensive step.
        if place_filter is not None and not place_matches(row, place_filter):
            continue
        if as_of is not None and not _matches_as_of(row, as_of):
            continue
        units = expand_legal_record(row) if locators else (row,)
        for atom in units:
            if locators and not _atom_matches(atom, locators):
                continue
            matched.append(atom)
            if retrieval is None and len(matched) >= limit:
                return tuple(matched)
    if retrieval:
        from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
            rank_section,
        )

        matched = list(rank_section(matched, retrieval=retrieval, text_query=text_query or ""))
    return tuple(matched[:limit])


def _matches_as_of(row: Mapping[str, object], as_of: str) -> bool:
    effective = row.get("effective_date")
    if not isinstance(effective, str):
        return False
    from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import (
        calendar_date,
    )

    parsed = calendar_date(effective)
    if parsed is None:
        return False
    return parsed <= as_of


def _atom_matches(atom: Mapping[str, object], locators: Mapping[str, str]) -> bool:
    raw = atom.get("provenance")
    provenance = raw if isinstance(raw, dict) else {}
    for key, want in locators.items():
        have = provenance.get(key)
        if not isinstance(have, str) or not have:
            return False
        if key == "subsection":
            tokens = {part.strip() for part in have.split(",") if part.strip()}
            needed = [part.strip() for part in want.split(",") if part.strip()]
            if not needed or any(part not in tokens for part in needed):
                return False
        elif have != want:
            return False
    return True


def _render_atoms(
    records: tuple[dict[str, object], ...],
    representation: str,
) -> tuple[dict[str, object], ...]:
    from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
        render_atomic,
    )

    return tuple(render_atomic(row, representation) for row in records)


def _render_view(
    records: tuple[dict[str, object], ...],
    representation: str,
) -> tuple[dict[str, object], ...]:
    from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
        expand_legal_record,
        render_atomic,
    )

    viewed: list[dict[str, object]] = []
    for row in records:
        for atom in expand_legal_record(row):
            viewed.append(render_atomic(atom, representation))
    return tuple(viewed)


def _stamp_fallback(row: dict[str, object], gap_status: str) -> dict[str, object]:
    copied = dict(row)
    raw = copied.get("provenance")
    provenance = dict(raw) if isinstance(raw, dict) else {}
    provenance["fallback_from"] = gap_status
    copied["provenance"] = provenance
    return copied


def _closed(echo: str) -> _Route:
    return _Route(echo, "not_published", None, None, None)


def _excluded_national(slug: str) -> bool:
    """National packs in ``EXCLUDED_SLUGS`` are not a published code.

    Municipal slugs are not compared here. ``belgium_municipal`` stays a
    municipal route even though ``belgium`` is excluded.
    """

    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
        EXCLUDED_SLUGS,
    )

    return fold_alias(slug) in EXCLUDED_SLUGS


def _alias_pair(slug: str) -> tuple[str, str] | None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.coverage import (
        ALIAS_TO_CANONICAL,
    )

    canonical = fold_alias(slug)
    for alias_key, canonical_value in ALIAS_TO_CANONICAL.items():
        if slug in {alias_key, canonical_value} or canonical == canonical_value:
            return alias_key, canonical_value
    return None


def _sha_match(pair: tuple[str | None, str | None] | None) -> bool:
    if pair is None:
        return False
    dataset_revision, source_sha = pair
    return (
        isinstance(dataset_revision, str)
        and isinstance(source_sha, str)
        and _SHA40.fullmatch(dataset_revision) is not None
        and dataset_revision == source_sha
    )


def _select_alias_slug(
    slug: str,
    revisions: Mapping[str, tuple[str | None, str | None]] | None,
) -> str:
    """Pick one spelling of an alias pair.

    Exactly one spelling whose manifest revision equals that spelling's own
    source SHA wins, including when it is the alias key. Both matches, neither
    match, and a missing report all select the canonical slug. This function
    does not open a dataset.
    """

    pair = _alias_pair(slug)
    if pair is None:
        return fold_alias(slug)
    alias_key, canonical = pair
    if revisions is None:
        return canonical
    if _sha_match(revisions.get(alias_key)) and not _sha_match(revisions.get(canonical)):
        return alias_key
    return canonical


def _jsonable_revisions(
    revisions: Mapping[str, tuple[str | None, str | None]] | None,
) -> dict[str, list[str | None] | None] | None:
    if revisions is None:
        return None
    encoded: dict[str, list[str | None] | None] = {}
    for key in sorted(revisions):
        pair = revisions[key]
        encoded[key] = None if pair is None else [pair[0], pair[1]]
    return encoded


def _stable_query_id(**fields: object) -> str:
    payload = {key: fields.get(key) for key in _QUERY_ID_FIELDS}
    raw_revisions = fields.get("alias_revisions")
    revisions = raw_revisions if isinstance(raw_revisions, Mapping) else None
    payload["alias_revisions"] = _jsonable_revisions(revisions)
    for key in _LOCATOR_QUERY_FIELDS + _PLACE_QUERY_FIELDS + _SEARCH_QUERY_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and value:
            payload[key] = value
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result(
    *,
    jurisdiction: str,
    coverage: str,
    source_repo: str | None,
    source_revision: str | None,
    records: tuple[dict[str, object], ...],
    query_id: str,
    place_name: str | None = None,
    place_state: str | None = None,
    place_latitude: str | None = None,
    place_longitude: str | None = None,
    place_ambiguous: bool = False,
    county_name: str | None = None,
    county_state: str | None = None,
    county_records: tuple[dict[str, object], ...] = (),
    territory_name: str | None = None,
    territory_state: str | None = None,
    territory_records: tuple[dict[str, object], ...] = (),
) -> LegalQueryResult:
    return LegalQueryResult(
        schema_version=_QUERY_SCHEMA,
        record_schema=_RECORD_SCHEMA,
        jurisdiction=jurisdiction,
        coverage=coverage,
        source_repo=source_repo,
        source_revision=source_revision,
        records=records,
        query_id=query_id,
        place_name=place_name,
        place_state=place_state,
        place_latitude=place_latitude,
        place_longitude=place_longitude,
        place_ambiguous=place_ambiguous,
        county_name=county_name,
        county_state=county_state,
        county_records=county_records,
        territory_name=territory_name,
        territory_state=territory_state,
        territory_records=territory_records,
    )


def _government_point(
    latitude: str | None,
    longitude: str | None,
    constraint: object,
) -> tuple[str | None, str | None]:
    """Point whose county applies: the caller's point, or the city's own."""

    if latitude and longitude:
        return latitude, longitude
    lat = getattr(constraint, "latitude", None)
    lon = getattr(constraint, "longitude", None)
    if isinstance(lat, str) and lat and isinstance(lon, str) and lon:
        return lat, lon
    return None, None


def _governments_at(route: _Route, latitude: str | None, longitude: str | None):
    from ipfs_datasets_py.processors.legal_data.county_geography import (
        LocationGovernments,
        locate_governments,
    )

    if not _us_municipal(route) or not latitude or not longitude:
        return LocationGovernments("none")
    return locate_governments(latitude, longitude)


def _city_fold(constraint: object) -> str | None:
    state = getattr(constraint, "state_code", None)
    name = getattr(constraint, "name", None)
    if not isinstance(state, str) or not isinstance(name, str):
        return None
    from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
        MunicipalSectionError,
        corpus_authority_fold,
    )

    try:
        return corpus_authority_fold(name, state)
    except MunicipalSectionError:
        return None


def _fold_skipped(skip: str | set[str | None] | None, fold: str) -> bool:
    if skip is None:
        return False
    if isinstance(skip, set):
        return fold in skip
    return fold == skip


def _present(
    rows: tuple[dict[str, object], ...],
    representation: str,
    locators: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    if locators:
        return _render_atoms(rows, representation)
    return _render_view(rows, representation)


def _layer_records(
    area: object,
    skip: str | set[str | None] | None,
    *,
    opened: tuple[dict[str, object], ...],
    limit: int,
    locators: Mapping[str, str],
    as_of: str | None,
    text_query: str | None,
    retrieval: str | None,
    load: bool,
) -> tuple[str | None, str | None, tuple[dict[str, object], ...]]:
    if area is None:
        return None, None, ()
    name = str(getattr(area, "name"))
    state = str(getattr(area, "state_code"))
    fold = getattr(area, "authority_fold", None)
    if not load or not isinstance(fold, str) or _fold_skipped(skip, fold):
        return name, state, ()
    pool = opened if _contains_authority(opened, fold, state) else _cached_authority_rows(fold, state)
    if not pool:
        return name, state, ()
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceConstraint,
    )

    rows = _select_records(
        pool,
        limit=limit,
        locators=locators,
        constraint=PlaceConstraint(name=fold, state_code=state),
        as_of=as_of,
        text_query=text_query,
        retrieval=retrieval,
    )
    return name, state, rows


def _contains_authority(
    opened: tuple[dict[str, object], ...],
    fold: str,
    state: str,
) -> bool:
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceConstraint,
        place_matches,
    )

    constraint = PlaceConstraint(name=fold, state_code=state)
    return any(place_matches(row, constraint) for row in opened)


@lru_cache(maxsize=8)
def _cached_authority_rows(name: str, state: str) -> tuple[dict[str, object], ...]:
    from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
        PlaceConstraint,
    )
    from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
        MunicipalSectionError,
        load_place_section,
    )

    try:
        return load_place_section(PlaceConstraint(name=name, state_code=state))
    except MunicipalSectionError:
        return ()
