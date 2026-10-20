"""County and territory that contain a requested coordinate.

The coordinate is the place whose law is requested. It is not the caller's
location. Polygons are the Census 2024 county cartographic boundary
(cb_2024_us_county_500k), stored as integer microdegrees. Connecticut
planning regions are not counties and are left unnamed. A point on a
shared border is not assigned. This module does not add a float column
to a legal record and does not download a corpus.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
    fold_place,
    microdegrees,
)

_INDEX_PATH = Path.home() / (
    ".ipfs_datasets/country-laws-ir/indexes/census-county-2024-500k.json"
)
_SOURCE = "cb_2024_us_county_500k"
_SCHEMA = "census-county-polygons/v1"
# Census LSAD codes that are a county or a county equivalent.
# "PL" is a Connecticut planning region and is not a county government.
_LEGAL_LSAD = frozenset({"00", "03", "04", "05", "06", "07", "10", "12", "13", "15", "25"})
_TERRITORIES = frozenset({"AS", "GU", "MP", "PR", "VI"})
_MICRO = 1_000_000
_SUFFIXES = (
    (" city and borough", "borough"),
    (" city and county", "county"),
    (" census area", "census area"),
    (" municipality", "municipality"),
    (" municipio", "municipio"),
    (" county", "county"),
    (" parish", "parish"),
    (" borough", "borough"),
    (" city", "city"),
)


class CountyGeographyError(FileNotFoundError):
    """The county boundary index or its Census source cannot be read."""


@dataclass(frozen=True)
class LocatedArea:
    """One government that contains the coordinate."""

    name: str
    state_code: str
    authority_fold: str | None


@dataclass(frozen=True)
class LocationGovernments:
    """City is resolved elsewhere. This is the county and the territory."""

    status: str
    county: LocatedArea | None = None
    territory: LocatedArea | None = None


@dataclass(frozen=True)
class _Area:
    name: str
    state_code: str
    state_name: str
    geoid: str
    lsad: str
    bbox: tuple[int, int, int, int]
    parts: tuple[tuple[tuple[tuple[int, int], ...], tuple[tuple[tuple[int, int], ...], ...]], ...]


def ring_contains(lon: int, lat: int, ring: tuple[tuple[int, int], ...]) -> bool:
    """True when the microdegree point is inside or on the ring."""

    if len(ring) < 4:
        return False
    inside = False
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        if _on_segment(lon, lat, x1, y1, x2, y2):
            return True
        if (y1 > lat) == (y2 > lat):
            continue
        dy = y2 - y1
        cross = (lon - x1) * dy - (lat - y1) * (x2 - x1)
        if dy > 0:
            if cross < 0:
                inside = not inside
        elif cross > 0:
            inside = not inside
    return inside


def build_county_index(source_dir: Path, dest: Path | None = None) -> Path:
    """Read a Census county shapefile directory and write the integer index."""

    shp = source_dir / f"{_SOURCE}.shp"
    dbf = source_dir / f"{_SOURCE}.dbf"
    if not shp.is_file() or not dbf.is_file():
        raise CountyGeographyError("Census county shapefile is not in the source directory")
    rows = _dbf_rows(dbf)
    shapes = _shp_rings(shp)
    if len(rows) != len(shapes):
        raise CountyGeographyError("Census county shapefile and table disagree")
    areas: list[dict[str, object]] = []
    for row, rings in zip(rows, shapes):
        if row["LSAD"] not in _LEGAL_LSAD or not rings:
            continue
        parts: list[list[object]] = []
        exterior: list[list[int]] | None = None
        holes: list[list[list[int]]] = []

        def flush() -> None:
            nonlocal exterior, holes
            if exterior is not None:
                parts.append([exterior, holes])
            exterior = None
            holes = []

        for ring in rings:
            encoded = [_micro_float(lon) for point in ring for lon in point]
            if _clockwise(ring):
                flush()
                exterior = encoded
                holes = []
            elif exterior is None:
                exterior = encoded
                holes = []
            else:
                holes.append(encoded)
        flush()
        if not parts:
            continue
        lons = [value for part in parts for value in part[0][0::2]]
        lats = [value for part in parts for value in part[0][1::2]]
        areas.append(
            {
                "n": row["NAMELSAD"],
                "s": row["STUSPS"],
                "t": row["STATE_NAME"],
                "g": row["GEOID"],
                "l": row["LSAD"],
                "b": [min(lons), min(lats), max(lons), max(lats)],
                "p": parts,
            }
        )
    payload = {"schema": _SCHEMA, "source": _SOURCE, "areas": areas}
    target = _INDEX_PATH if dest is None else dest
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    _load_areas.cache_clear()
    return target


def locate_governments(latitude: str, longitude: str) -> LocationGovernments:
    """County and territory containing this coordinate, or none."""

    lat = microdegrees(latitude)
    lon = microdegrees(longitude)
    if lat is None or lon is None:
        return LocationGovernments("unindexed")
    try:
        areas, grid = _load_areas()
    except CountyGeographyError:
        return LocationGovernments("unindexed")
    found: list[_Area] = []
    for index in grid.get((lon // _MICRO, lat // _MICRO), ()):
        area = areas[index]
        min_lon, min_lat, max_lon, max_lat = area.bbox
        if lon < min_lon or lon > max_lon or lat < min_lat or lat > max_lat:
            continue
        if _area_contains(area, lon, lat):
            found.append(area)
    if not found:
        return LocationGovernments("none")
    if len(found) > 1:
        return LocationGovernments("ambiguous")
    area = found[0]
    territory = None
    if area.state_code in _TERRITORIES:
        territory = LocatedArea(
            name=area.state_name,
            state_code=area.state_code,
            authority_fold=_corpus_fold(area.state_name, area.state_code),
        )
    return LocationGovernments(
        "one",
        county=LocatedArea(
            name=area.name,
            state_code=area.state_code,
            authority_fold=_corpus_fold(area.name, area.state_code),
        ),
        territory=territory,
    )


def _corpus_fold(name: str, state_code: str) -> str | None:
    try:
        from ipfs_datasets_py.processors.legal_data.municipal_section_search import (
            MunicipalSectionError,
            load_authority_index,
        )
    except ImportError:
        return None
    try:
        index = load_authority_index()
    except MunicipalSectionError:
        return None
    folded = fold_place(name)
    if _rows(index, folded, state_code):
        return folded
    bare = folded
    kind = ""
    for suffix, label in _SUFFIXES:
        if folded.endswith(suffix):
            bare = folded[: -len(suffix)].strip()
            kind = label
            break
    if not bare:
        return None
    forms = [bare]
    if kind == "county":
        forms.extend((f"city and county of {bare}", f"{bare} county"))
    elif kind == "borough":
        forms.extend((f"city and borough of {bare}", f"{bare} borough"))
    elif kind == "municipality":
        forms.extend((f"municipality of {bare}", f"{bare} municipality"))
    elif kind == "city":
        forms.extend((f"city of {bare}", f"{bare} city"))
    elif kind == "parish":
        forms.append(f"{bare} parish")
    elif kind == "census area":
        forms.append(f"{bare} census area")
    elif kind == "municipio":
        forms.append(f"municipio de {bare}")
    found: list[str] = []
    seen = {folded}
    for form in forms:
        if form in seen:
            continue
        seen.add(form)
        if _rows(index, form, state_code):
            found.append(form)
    if kind:
        typed = [form for form in found if kind in form]
        if len(typed) == 1:
            return typed[0]
        if len(typed) > 1:
            return None
    if len(found) == 1:
        return found[0]
    return None


def _rows(index: Mapping[str, Mapping[str, object]], folded: str, state_code: str) -> bool:
    slot = index.get(f"{folded}\tUS-{state_code}")
    rows = slot.get("rows") if isinstance(slot, Mapping) else 0
    return isinstance(rows, int) and rows > 0


def _area_contains(area: _Area, lon: int, lat: int) -> bool:
    for exterior, holes in area.parts:
        if not ring_contains(lon, lat, exterior):
            continue
        if any(ring_contains(lon, lat, hole) for hole in holes):
            continue
        return True
    return False


@lru_cache(maxsize=1)
def _load_areas() -> tuple[tuple[_Area, ...], dict[tuple[int, int], tuple[int, ...]]]:
    if not _INDEX_PATH.is_file():
        raise CountyGeographyError("county boundary index is not on this machine")
    payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
        raise CountyGeographyError("county boundary index schema does not match")
    raw_areas = payload.get("areas")
    if not isinstance(raw_areas, list):
        raise CountyGeographyError("county boundary index has no areas")
    areas: list[_Area] = []
    grid: dict[tuple[int, int], list[int]] = {}
    for raw in raw_areas:
        if not isinstance(raw, dict):
            continue
        bbox_raw = raw.get("b")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        parts: list[tuple[tuple[tuple[int, int], ...], tuple[tuple[tuple[int, int], ...], ...]]] = []
        for part in raw.get("p") or []:
            if not isinstance(part, list) or len(part) != 2:
                continue
            exterior = _pairs(part[0])
            holes = tuple(_pairs(hole) for hole in part[1] or [])
            if exterior:
                parts.append((exterior, holes))
        if not parts:
            continue
        areas.append(
            _Area(
                name=str(raw.get("n") or ""),
                state_code=str(raw.get("s") or ""),
                state_name=str(raw.get("t") or ""),
                geoid=str(raw.get("g") or ""),
                lsad=str(raw.get("l") or ""),
                bbox=bbox,
                parts=tuple(parts),
            )
        )
        index = len(areas) - 1
        min_lon, min_lat, max_lon, max_lat = bbox
        for lon_cell in range(min_lon // _MICRO, max_lon // _MICRO + 1):
            for lat_cell in range(min_lat // _MICRO, max_lat // _MICRO + 1):
                grid.setdefault((lon_cell, lat_cell), []).append(index)
    frozen = {key: tuple(value) for key, value in grid.items()}
    return tuple(areas), frozen


def _pairs(flat: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(flat, list) or len(flat) < 2:
        return ()
    return tuple((int(flat[index]), int(flat[index + 1])) for index in range(0, len(flat) - 1, 2))


def _on_segment(lon: int, lat: int, x1: int, y1: int, x2: int, y2: int) -> bool:
    cross = (x2 - x1) * (lat - y1) - (y2 - y1) * (lon - x1)
    if cross != 0:
        return False
    return min(x1, x2) <= lon <= max(x1, x2) and min(y1, y2) <= lat <= max(y1, y2)


def _clockwise(ring: Iterable[tuple[float, float]]) -> bool:
    points = list(ring)
    area = 0
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        area += x1 * y2 - x2 * y1
    return area < 0


def _micro_float(value: float) -> int:
    return int(round(value * _MICRO))


def _dbf_rows(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    count, header_len, record_len = struct.unpack_from("<IHH", data, 4)
    fields: list[tuple[str, int]] = []
    cursor = 32
    while cursor < header_len - 1 and data[cursor] != 0x0D:
        name = data[cursor : cursor + 11].split(b"\x00", 1)[0].decode("ascii")
        fields.append((name, data[cursor + 16]))
        cursor += 32
    rows: list[dict[str, str]] = []
    for index in range(count):
        record = data[header_len + index * record_len : header_len + (index + 1) * record_len]
        offset = 1
        row: dict[str, str] = {}
        for name, length in fields:
            raw = record[offset : offset + length]
            offset += length
            row[name] = raw.decode("utf-8").strip()
        rows.append(row)
    return rows


def _shp_rings(path: Path) -> list[list[list[tuple[float, float]]]]:
    data = path.read_bytes()
    cursor = 100
    shapes: list[list[list[tuple[float, float]]]] = []
    while cursor + 8 <= len(data):
        _number, words = struct.unpack_from(">II", data, cursor)
        cursor += 8
        end = cursor + words * 2
        if end > len(data) or cursor + 4 > end:
            break
        shape_type = struct.unpack_from("<i", data, cursor)[0]
        if shape_type == 0:
            shapes.append([])
            cursor = end
            continue
        if shape_type != 5:
            raise CountyGeographyError(f"unsupported county shape type {shape_type}")
        parts_count, point_count = struct.unpack_from("<2i", data, cursor + 36)
        part_at = cursor + 44
        parts = struct.unpack_from(f"<{parts_count}i", data, part_at)
        point_at = part_at + 4 * parts_count
        points = [
            struct.unpack_from("<2d", data, point_at + index * 16)
            for index in range(point_count)
        ]
        rings: list[list[tuple[float, float]]] = []
        for index, start in enumerate(parts):
            stop = parts[index + 1] if index + 1 < len(parts) else point_count
            rings.append([(float(x), float(y)) for x, y in points[start:stop]])
        shapes.append(rings)
        cursor = end
    return shapes
