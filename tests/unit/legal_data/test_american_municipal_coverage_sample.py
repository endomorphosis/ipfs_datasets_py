"""Statistical sample of the local American municipal v4 tree.

Every 17th shard is read, 51 shards and about 1,020,000 rows, roughly 6
percent of the 17,109,461-row snapshot 24cac8b72a91. The scan checks that
place, jurisdiction, citation, language, dates, and locators are present in
the proportions of this tree. One real row from each sampled state is then
queried back by place, locator, date, and, when the seed point is unique,
by coordinates.

The product pin stays unsearchable. The query flag is set only inside the
test. Ordinance text is not loaded; place and date are rejected before the
text expander runs.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.municipal_place_query import (
    fold_place,
    municipal_places,
)
from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    query_legal_records,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    STATE_NAME,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import calendar_date

_TREE = Path(
    "/home/barberb/.ipfs_datasets/country-laws-ir/norm-export/"
    "24cac8b72a91f1c196bef47a8bd0398b103f26ba/american_municipal_law_v4"
)
_PIN = "c" * 40
_STRIDE = 17
_COLUMNS = (
    "authority",
    "jurisdiction",
    "effective_date",
    "citation",
    "entry_cid",
    "provenance",
    "language",
)


@dataclass
class CoverageSample:
    rows: int = 0
    parts: int = 0
    dated: int = 0
    sectioned: int = 0
    titled: int = 0
    chaptered: int = 0
    subsectioned: int = 0
    authorities: int = 0
    states: frozenset[str] = field(default_factory=frozenset)
    auth_missing: int = 0
    jurisdiction_missing: int = 0
    bare_us: int = 0
    bad_jurisdiction: int = 0
    bad_date: int = 0
    citation_missing: int = 0
    language_not_en: int = 0
    bad_provenance: int = 0
    section_rows: dict[str, dict[str, object]] = field(default_factory=dict)
    dated_rows: dict[str, dict[str, object]] = field(default_factory=dict)
    plain_rows: dict[str, dict[str, object]] = field(default_factory=dict)


def _provenance(row: dict[str, object]) -> dict[str, object] | None:
    raw = row.get("provenance")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _valid_date(value: object) -> bool:
    if calendar_date(value) is None or not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _scan() -> CoverageSample:
    import pyarrow.parquet as pq

    if not (_TREE / "manifest.json").is_file():
        pytest.skip("local american v4 tree is not on this machine")
    manifest = json.loads((_TREE / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("normalizer_version") != "american-municipal-html/v4+legal-record/v1":
        pytest.fail("sample tree is not american-municipal-html/v4")
    if manifest.get("rows_kept") != 17109461:
        pytest.fail("sample tree does not have the v4 row count")
    parts = sorted((_TREE / "data").glob("part-*/laws.parquet"))
    chosen = parts[::_STRIDE]
    sample = CoverageSample(parts=len(chosen))
    names: set[str] = set()
    state_counts: Counter[str] = Counter()
    for path in chosen:
        table = pq.read_table(path, columns=list(_COLUMNS))
        columns = {name: table.column(name).to_pylist() for name in _COLUMNS}
        sample.rows += table.num_rows
        for index in range(table.num_rows):
            row = {name: columns[name][index] for name in _COLUMNS}
            _tally(sample, row, names, state_counts)
    sample.authorities = len(names)
    sample.states = frozenset(state_counts)
    return sample


def _tally(
    sample: CoverageSample,
    row: dict[str, object],
    names: set[str],
    state_counts: Counter[str],
) -> None:
    authority = row.get("authority")
    jurisdiction = row.get("jurisdiction")
    if isinstance(authority, str) and authority.strip():
        names.add(authority)
    else:
        sample.auth_missing += 1
    if jurisdiction == "US":
        sample.bare_us += 1
    elif (
        isinstance(jurisdiction, str)
        and len(jurisdiction) == 5
        and jurisdiction.startswith("US-")
        and jurisdiction[3:] in STATE_NAME
    ):
        state_counts[jurisdiction] += 1
    elif not jurisdiction:
        sample.jurisdiction_missing += 1
    else:
        sample.bad_jurisdiction += 1
    effective = row.get("effective_date")
    if effective:
        sample.dated += 1
        if not _valid_date(effective):
            sample.bad_date += 1
    if not row.get("citation"):
        sample.citation_missing += 1
    if row.get("language") != "en":
        sample.language_not_en += 1
    provenance = _provenance(row)
    if provenance is None:
        sample.bad_provenance += 1
        return
    state = jurisdiction if isinstance(jurisdiction, str) else ""
    if provenance.get("section"):
        sample.sectioned += 1
        sample.section_rows.setdefault(state, row)
    if provenance.get("title"):
        sample.titled += 1
    if provenance.get("chapter"):
        sample.chaptered += 1
    if provenance.get("subsection"):
        sample.subsectioned += 1
    if effective and _valid_date(effective):
        sample.dated_rows.setdefault(state, row)
    sample.plain_rows.setdefault(state, row)


@pytest.fixture(scope="module")
def coverage() -> CoverageSample:
    return _scan()


@pytest.fixture
def opened(monkeypatch, coverage):
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")

    def readable(repo: str) -> bool:
        return repo == "american_municipal_law_norm"

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        readable,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_revision",
        lambda repo: _PIN if repo == "american_municipal_law_norm" else None,
    )

    def run(rows: tuple[dict[str, object], ...], **kwargs: object):
        def opener(repo: str) -> tuple[dict[str, object], ...]:
            assert repo == "justicedao/american_municipal_law_norm"
            return rows

        return query_legal_records(
            jurisdiction="US",
            limit=20,
            corpus_opener=opener,
            **kwargs,  # type: ignore[arg-type]
        )

    return run


def _rate(found: int, rows: int) -> float:
    return found / rows


def test_stride_sample_covers_place_date_and_locators(coverage: CoverageSample) -> None:
    assert coverage.parts == 51
    assert coverage.rows > 900_000
    assert coverage.auth_missing == 0
    assert coverage.jurisdiction_missing == 0
    assert coverage.bare_us == 0
    assert coverage.bad_jurisdiction == 0
    assert coverage.bad_date == 0
    assert coverage.citation_missing == 0
    assert coverage.language_not_en == 0
    assert coverage.bad_provenance == 0
    assert len(coverage.states) >= 40
    assert coverage.authorities >= 500
    dated = _rate(coverage.dated, coverage.rows)
    sectioned = _rate(coverage.sectioned, coverage.rows)
    chaptered = _rate(coverage.chaptered, coverage.rows)
    titled = _rate(coverage.titled, coverage.rows)
    subsectioned = _rate(coverage.subsectioned, coverage.rows)
    assert 0.24 <= dated <= 0.33, dated
    assert 0.84 <= sectioned <= 0.92, sectioned
    assert 0.55 <= chaptered <= 0.65, chaptered
    assert 0.28 <= titled <= 0.36, titled
    assert 0.18 <= subsectioned <= 0.28, subsectioned
    assert len(coverage.section_rows) >= 40


def _place_query(row: dict[str, object]) -> str:
    jurisdiction = str(row["jurisdiction"])
    state = STATE_NAME[jurisdiction[3:]]
    return f"{row['authority']}, {state}"


def _locators(row: dict[str, object]) -> dict[str, str]:
    provenance = _provenance(row) or {}
    selected: dict[str, str] = {}
    for key in ("title", "chapter", "section"):
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            selected[key] = value.strip()
    subsection = provenance.get("subsection")
    if isinstance(subsection, str) and subsection.strip():
        token = subsection.split(",")[0].strip()
        if token:
            selected["subsection"] = token
    return selected


def _decoys(coverage: CoverageSample, jurisdiction: str) -> tuple[dict[str, object], ...]:
    chosen: list[dict[str, object]] = []
    for state, row in coverage.plain_rows.items():
        if state == jurisdiction:
            continue
        chosen.append(row)
        if len(chosen) == 4:
            break
    return tuple(chosen)


def _day_before(value: str) -> str:
    return (date.fromisoformat(value) - timedelta(days=1)).isoformat()


def test_each_sampled_state_round_trips(coverage: CoverageSample, opened) -> None:
    checked = 0
    dated_checked = 0
    failures: list[str] = []
    for state, row in sorted(coverage.section_rows.items()):
        locators = _locators(row)
        if "section" not in locators:
            continue
        batch = (row, *_decoys(coverage, state))
        found = opened(batch, place=_place_query(row), **locators)
        cids = [item["entry_cid"] for item in found.records]
        if cids != [row["entry_cid"]]:
            failures.append(f"{state} section returned {cids}")
        missed = opened(batch, place=_place_query(row), section="not-a-section")
        if missed.records:
            failures.append(f"{state} wrong section returned rows")
        if found.records:
            hit = found.records[0]
            if hit.get("citation") != row.get("citation"):
                failures.append(f"{state} citation changed")
            if hit.get("authority") != row.get("authority"):
                failures.append(f"{state} authority changed")
            if hit.get("jurisdiction") != row.get("jurisdiction"):
                failures.append(f"{state} jurisdiction changed")
        checked += 1
        dated = coverage.dated_rows.get(state)
        if dated is None or not isinstance(dated.get("effective_date"), str):
            continue
        when = str(dated["effective_date"])
        dated_batch = (dated, *_decoys(coverage, state))
        on_day = opened(
            dated_batch,
            place=_place_query(dated),
            as_of=when,
        )
        before = opened(
            dated_batch,
            place=_place_query(dated),
            as_of=_day_before(when),
        )
        if dated["entry_cid"] not in {item["entry_cid"] for item in on_day.records}:
            failures.append(f"{state} missing on {when}")
        if before.records:
            failures.append(f"{state} returned a row before {when}")
        dated_checked += 1
    assert checked >= 40, checked
    assert dated_checked >= 40, dated_checked
    assert failures == [], failures


def test_unique_coordinates_round_trip(coverage: CoverageSample, opened) -> None:
    points: dict[tuple[int, int], list[object]] = {}
    for place in municipal_places():
        points.setdefault((place.lat_micro, place.lon_micro), []).append(place)
    attempts = 0
    failures: list[str] = []
    for state, row in sorted(coverage.section_rows.items()):
        authority = row.get("authority")
        jurisdiction = row.get("jurisdiction")
        if not isinstance(authority, str) or not isinstance(jurisdiction, str):
            continue
        code = jurisdiction[3:]
        matches = [
            place
            for place in municipal_places()
            if place.state_code == code and fold_place(place.name) == fold_place(authority)
        ]
        if len(matches) != 1:
            continue
        place = matches[0]
        if len(points.get((place.lat_micro, place.lon_micro), [])) != 1:
            continue
        attempts += 1
        batch = (row, *_decoys(coverage, jurisdiction))
        found = opened(batch, latitude=place.latitude, longitude=place.longitude)
        cids = {item["entry_cid"] for item in found.records}
        if (
            found.place_name != authority
            or found.place_state != code
            or row["entry_cid"] not in cids
        ):
            failures.append(
                f"{state} {authority!r} resolved {found.place_name!r} "
                f"{found.place_state} cid_hit={row['entry_cid'] in cids}"
            )
    assert attempts >= 20, attempts
    assert failures == [], failures
