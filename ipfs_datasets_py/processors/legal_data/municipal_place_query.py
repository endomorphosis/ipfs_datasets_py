"""Resolve a requested municipality from a name, coordinates, or both.

The coordinates are the place whose ordinance is requested. They are not
the caller's location. The primary GNIS seed supplies the point for each
US municipal place. A world municipal point is the nearest stored place
in the named country, read from the local coordinate parquet. Alternate
GNIS ids are not used. Nothing in this module reads an address, an IP,
a locale, or a timezone.

Distances are integer meters. Seed latitudes and longitudes stay decimal
strings, so a legal record does not gain a float column.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Sequence

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    STATE_NAME,
)

# A city point more than this far from the requested coordinate is not a match.
MAX_PLACE_METERS = 25_000
_METERS_PER_DEGREE = 111_320
_MICRO = 1_000_000
# Cosine of 0..90 degrees, in millionths, for the longitude scale.
_COS_MICRO = (
    1000000, 999848, 999391, 998630, 997564, 996195, 994522, 992546, 990268,
    987688, 984808, 981627, 978148, 974370, 970296, 965926, 961262, 956305,
    951057, 945519, 939693, 933580, 927184, 920505, 913545, 906308, 898794,
    891007, 882948, 874620, 866025, 857167, 848048, 838671, 829038, 819152,
    809017, 798636, 788011, 777146, 766044, 754710, 743145, 731354, 719340,
    707107, 694658, 681998, 669131, 656059, 642788, 629320, 615661, 601815,
    587785, 573576, 559193, 544639, 529919, 515038, 500000, 484810, 469472,
    453990, 438371, 422618, 406737, 390731, 374607, 358368, 342020, 325568,
    309017, 292372, 275637, 258819, 241922, 224951, 207912, 190809, 173648,
    156434, 139173, 121869, 104528, 87156, 69756, 52336, 34899, 17452, 0,
)
_DECIMAL = re.compile(r"[+-]?(?:\d+\.\d+|\d+)")
_PREFIXES = (
    "city of ",
    "town of ",
    "village of ",
    "municipality of ",
    "borough of ",
)
_NAME_TO_CODE = {name.casefold(): code for code, name in STATE_NAME.items()}


class PlaceQueryError(ValueError):
    """A place request that cannot be resolved without guessing."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MunicipalPlace:
    """One primary seed place. Coordinates are the seed's decimal text."""

    name: str
    state_code: str
    latitude: str
    longitude: str
    lat_micro: int
    lon_micro: int
    gnis: str


@dataclass(frozen=True)
class PlaceConstraint:
    """Row filter. A missing state matches the authority name only."""

    name: str
    state_code: str | None
    latitude: str | None = None
    longitude: str | None = None


@dataclass(frozen=True)
class WorldMunicipalPlace:
    """One stored world place. ``jurisdiction`` is the country code."""

    name: str
    jurisdiction: str
    latitude: str
    longitude: str
    lat_micro: int
    lon_micro: int
    qid: str


def _seed_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "legal_scrapers"
        / "municipal"
        / "seeds"
        / "americas"
        / "US.jsonl"
    )


def microdegrees(value: str) -> int | None:
    """Decimal degrees as integer millionths, or None when the text is not decimal."""

    text = value.strip()
    if _DECIMAL.fullmatch(text) is None:
        return None
    sign = -1 if text.startswith("-") else 1
    body = text[1:] if text[0] in "+-" else text
    whole, dot, frac = body.partition(".")
    digits = (frac + "0000000")[:7] if dot else "0000000"
    micro = int(whole) * _MICRO + int(digits[:6])
    if digits[6] >= "5":
        micro += 1
    return sign * micro


def distance_meters(lat_a: int, lon_a: int, lat_b: int, lon_b: int) -> int:
    """Equirectangular distance in whole meters between two microdegree points."""

    average = abs((lat_a + lat_b) // 2) // _MICRO
    if average > 90:
        average = 90
    east = (lon_a - lon_b) * _COS_MICRO[average] // _MICRO
    north = lat_a - lat_b
    return math.isqrt(east * east + north * north) * _METERS_PER_DEGREE // _MICRO


def parse_coordinates(
    latitude: object,
    longitude: object,
) -> tuple[str | None, str | None]:
    """Return stripped decimal strings, or nothing when both sides are absent."""

    if latitude is None and longitude is None:
        return None, None
    if latitude is None or longitude is None:
        raise PlaceQueryError("coordinates")
    if not isinstance(latitude, str):
        raise PlaceQueryError("latitude")
    if not isinstance(longitude, str):
        raise PlaceQueryError("longitude")
    lat = latitude.strip()
    lon = longitude.strip()
    if not lat and not lon:
        return None, None
    if not lat or not lon:
        raise PlaceQueryError("coordinates")
    lat_micro = microdegrees(lat)
    lon_micro = microdegrees(lon)
    if lat_micro is None or lat_micro < -90 * _MICRO or lat_micro > 90 * _MICRO:
        raise PlaceQueryError("latitude")
    if lon_micro is None or lon_micro < -180 * _MICRO or lon_micro > 180 * _MICRO:
        raise PlaceQueryError("longitude")
    return lat, lon


def fold_place(value: str) -> str:
    """Case-fold a place name and drop periods. Saint and St stay different."""

    return " ".join(value.casefold().replace(".", " ").split())


def prefix_folds(folded: str) -> tuple[str, ...]:
    """Folds one allowed municipal prefix away from ``folded``.

    The prefixes are city, town, village, municipality, and borough of.
    A county name, and a city-and-county name, are not prefixes.
    """

    found: list[str] = []
    seen = {folded}
    for prefix in _PREFIXES:
        if folded.startswith(prefix):
            bare = folded[len(prefix) :].strip()
            if bare and bare not in seen:
                seen.add(bare)
                found.append(bare)
        longer = f"{prefix}{folded}"
        if longer not in seen:
            seen.add(longer)
            found.append(longer)
    return tuple(found)


def _split_place(value: str) -> tuple[str, str | None]:
    text = value.strip()
    if "," not in text:
        return text, None
    left, right = text.rsplit(",", 1)
    token = right.strip()
    if len(token) == 2 and token.isalpha() and token.upper() in STATE_NAME:
        return left.strip(), token.upper()
    code = _NAME_TO_CODE.get(token.casefold())
    if code is not None:
        return left.strip(), code
    return text, None


@lru_cache(maxsize=1)
def municipal_places() -> tuple[MunicipalPlace, ...]:
    """Primary GNIS places that have a name, a known state, and both coordinates."""

    path = _seed_path()
    found: list[MunicipalPlace] = []
    if not path.is_file():
        return ()
    for line in path.open(encoding="utf-8"):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text, parse_float=str, parse_int=str)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        place = _place_from_row(row)
        if place is not None:
            found.append(place)
    return tuple(found)


def _place_from_row(row: dict[str, object]) -> MunicipalPlace | None:
    name = str(row.get("name") or "").strip()
    state = str(row.get("state_code") or "").strip().upper()
    latitude = str(row.get("lat") or "").strip()
    longitude = str(row.get("lon") or "").strip()
    gnis = str(row.get("gnis") or "").strip()
    if not name or state not in STATE_NAME or not gnis:
        return None
    lat_micro = microdegrees(latitude)
    lon_micro = microdegrees(longitude)
    if lat_micro is None or lon_micro is None:
        return None
    return MunicipalPlace(
        name=name,
        state_code=state,
        latitude=latitude,
        longitude=longitude,
        lat_micro=lat_micro,
        lon_micro=lon_micro,
        gnis=gnis,
    )


def _named_candidates(
    place: str,
    places: Sequence[MunicipalPlace],
) -> list[MunicipalPlace]:
    name, state = _split_place(place)
    folded = fold_place(name)
    if not folded:
        return []
    exact = [
        item
        for item in places
        if fold_place(item.name) == folded and (state is None or item.state_code == state)
    ]
    if exact:
        return exact
    prefixed: list[MunicipalPlace] = []
    for item in places:
        if state is not None and item.state_code != state:
            continue
        seed_name = fold_place(item.name)
        if any(seed_name == prefix + folded for prefix in _PREFIXES):
            prefixed.append(item)
    return prefixed


def _closest(
    candidates: Sequence[Any],
    lat_micro: int,
    lon_micro: int,
    tie: Callable[[Any], tuple[str, ...]],
) -> Any:
    """Nearest place within ``MAX_PLACE_METERS``. An equal distance is ambiguous."""

    def meters(item: Any) -> int:
        return distance_meters(item.lat_micro, item.lon_micro, lat_micro, lon_micro)

    close = [item for item in candidates if meters(item) <= MAX_PLACE_METERS]
    if not close:
        return None
    ranked = sorted(close, key=lambda item: (meters(item),) + tie(item))
    if len(ranked) > 1 and meters(ranked[0]) == meters(ranked[1]):
        raise PlaceQueryError("ambiguous_place")
    return ranked[0]


def _nearest(
    candidates: Sequence[MunicipalPlace],
    lat_micro: int,
    lon_micro: int,
) -> MunicipalPlace | None:
    found = _closest(
        candidates,
        lat_micro,
        lon_micro,
        tie=lambda item: (item.state_code, item.name, item.gnis),
    )
    if not isinstance(found, MunicipalPlace):
        return None
    return found


def resolve_municipal_place(
    place: str | None,
    latitude: str | None,
    longitude: str | None,
    places: Sequence[MunicipalPlace] | None = None,
) -> MunicipalPlace | None:
    """Return one seed place, or None when no seed place is within range.

    A name that matches several seed places raises ``ambiguous_place`` unless
    the coordinates select one of those names within ``MAX_PLACE_METERS``.
    Coordinates never switch the request to a different name.
    """

    table = municipal_places() if places is None else places
    lat_micro = microdegrees(latitude) if latitude else None
    lon_micro = microdegrees(longitude) if longitude else None
    if place:
        candidates = _named_candidates(place, table)
        if not candidates:
            return None
        if lat_micro is None or lon_micro is None:
            if len(candidates) > 1:
                raise PlaceQueryError("ambiguous_place")
            return candidates[0]
        return _nearest(candidates, lat_micro, lon_micro)
    if lat_micro is None or lon_micro is None:
        return None
    return _nearest(table, lat_micro, lon_micro)


def _world_coord_path() -> Path:
    configured = os.environ.get("MUNICIPAL_NORM_ROOT", "").strip()
    root = Path(configured) if configured else Path("/storage/hf_cache/municipal-collection/e1bdd7b0")
    return root / "place-coords.parquet"


def load_world_municipal_places(jurisdiction: str) -> tuple[WorldMunicipalPlace, ...]:
    """Places for one country from the local coordinate parquet.

    The file is built offline. This read does not contact Wikidata or the
    Hub. A missing file is an empty country, the same as a seed file that
    is not on disk.
    """

    path = _world_coord_path()
    if not path.is_file():
        return ()
    code = jurisdiction.strip().upper()
    try:
        import pyarrow.parquet as pq
        from pyarrow.lib import ArrowException

        table = pq.read_table(
            path,
            columns=["authority", "latitude", "longitude", "lat_micro", "lon_micro", "qid"],
            filters=[("jurisdiction", "=", code)],
        )
        rows = list(
            zip(
                *(
                    table.column(name).to_pylist()
                    for name in (
                        "authority",
                        "latitude",
                        "longitude",
                        "lat_micro",
                        "lon_micro",
                        "qid",
                    )
                )
            )
        )
    except (OSError, ArrowException, ValueError):
        return ()
    found: list[WorldMunicipalPlace] = []
    for name, latitude, longitude, lat_micro, lon_micro, qid in rows:
        if not isinstance(name, str) or not name.strip():
            continue
        if lat_micro is None or lon_micro is None or not qid:
            continue
        found.append(
            WorldMunicipalPlace(
                name=name,
                jurisdiction=code,
                latitude=str(latitude),
                longitude=str(longitude),
                lat_micro=int(lat_micro),
                lon_micro=int(lon_micro),
                qid=str(qid),
            )
        )
    return tuple(found)


def resolve_world_municipal_place(
    jurisdiction: str,
    place: str | None,
    latitude: str | None,
    longitude: str | None,
    places: Sequence[WorldMunicipalPlace] | None = None,
) -> PlaceConstraint | None:
    """Nearest stored municipality in ``jurisdiction`` within 25 km.

    Coordinates never select another country and never switch the request
    to a different name. The constraint carries that place's own point and
    leaves ``state_code`` unset, so a world row is not filtered as a US state.
    """

    code = jurisdiction.strip().upper()
    table = load_world_municipal_places(code) if places is None else places
    in_country = [item for item in table if item.jurisdiction == code]
    if place:
        folded = fold_place(place)
        if not folded:
            return None
        candidates = [item for item in in_country if fold_place(item.name) == folded]
        if not candidates:
            return None
    else:
        candidates = in_country
    lat_micro = microdegrees(latitude) if latitude else None
    lon_micro = microdegrees(longitude) if longitude else None
    if lat_micro is None or lon_micro is None:
        return None
    found = _closest(
        candidates,
        lat_micro,
        lon_micro,
        tie=lambda item: (item.name, item.qid),
    )
    if not isinstance(found, WorldMunicipalPlace):
        return None
    return PlaceConstraint(
        name=found.name,
        state_code=None,
        latitude=found.latitude,
        longitude=found.longitude,
    )


def authority_constraint(place: str) -> PlaceConstraint:
    """Match a record authority when the name is not a unique seed place.

    Metadata can name a place the primary seed does not list. The state
    suffix still limits the record jurisdiction. County names are not
    invented from a city name.
    """

    name, state = _split_place(place)
    return PlaceConstraint(name=name, state_code=state)


def constraint_from_place(place: MunicipalPlace) -> PlaceConstraint:
    return PlaceConstraint(
        name=place.name,
        state_code=place.state_code,
        latitude=place.latitude,
        longitude=place.longitude,
    )


def place_matches(row: dict[str, object], constraint: PlaceConstraint) -> bool:
    """True when the row authority is this place and, when known, this state.

    An exact folded name matches before any index is read. When that
    exact authority has no rows and exactly one in-state name is a
    single allowed prefix away, that stored authority matches too.
    Two governments that both have rows stay separate.
    """

    authority = row.get("authority")
    if not isinstance(authority, str):
        return False
    folded_row = fold_place(authority)
    folded_name = fold_place(constraint.name)
    if constraint.state_code is not None and row.get("jurisdiction") != f"US-{constraint.state_code}":
        return False
    if folded_row == folded_name:
        return True
    if constraint.state_code is None:
        return False
    from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
        MunicipalSectionError,
        corpus_authority_fold,
    )

    try:
        chosen = corpus_authority_fold(constraint.name, constraint.state_code)
    except MunicipalSectionError:
        return False
    return chosen == folded_row
