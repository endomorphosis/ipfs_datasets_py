"""Keyword search over legal text by vector similarity and graph walk.

The query is embedded and compared with loaded vector probes. The top
probes are then expanded one hop through the knowledge graph. Document
text and embedding tables are not stored in the catalog. A jurisdiction,
level, and instrument with no selected corpus is a scraper gap.

``hash_embed`` is the offline keyword encoder. A caller can pass a model
encoder instead. Neither path downloads a corpus.

``sample_corpus_gaps`` still draws from every empty cell, including
combinations that are not laws. ``corpus_work_todo`` is the queue: index
the corpora we already have, scrape municipal ordinances where a national
statute index exists, and leave county patents and the other empty
combinations off the scraper list. The readable list is
``processors/legal_data/legal_corpus_gap_todo.md``.

An index job names its publish repo with ``justicedao_index_repo``. That
repo is always on the ``justicedao`` org. Source text on another org is
left in place. ``justicedao/ipfs_state_laws`` and
``justicedao/ipfs_federal_register`` are never the publish target.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ipfs_datasets_py.ducklake.legal_dataset_schema import (
    DatasetSchema,
    _canonical_jurisdiction_key,
    _corpus_jurisdiction_key,
    _level_matches,
    _matches_jurisdiction,
    corpus_admin_level,
    legal_dataset_schema,
    request_legal_data,
)
from ipfs_datasets_py.ducklake.legal_search_catalog import LegalSearchCatalogError
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    CorpusRelease,
)

_INSTRUMENTS = (
    "case",
    "statute",
    "ordinance",
    "regulation",
    "rule",
    "court",
    "register",
    "patent",
    "order",
    "form",
)
_LEVELS = ("national", "state", "county", "municipal")
_GRAPH_HOP = 0.5


@dataclass(frozen=True)
class VectorProbe:
    """One loaded vector. Coordinates are the encoder's unit vector."""

    corpus_id: str
    entry_cid: str
    coordinates: tuple[float, ...]


@dataclass(frozen=True)
class GraphEdge:
    """One knowledge-graph edge. The walk does not read node text."""

    corpus_id: str
    source_cid: str
    target_cid: str
    relation: str


@dataclass(frozen=True)
class SearchHit:
    """A vector or graph hit. The score is not a document body."""

    corpus_id: str
    hf_repo: str
    entry_cid: str
    instrument_kind: str
    admin_level: str
    channel: str
    score: float
    relation: str | None = None
    research_only: bool = True
    authoritative: bool = False
    ducklake_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative or self.ducklake_authoritative or not self.research_only:
            raise LegalSearchCatalogError("search pin must stay observational")
        if self.channel not in {"vector", "graph"}:
            raise LegalSearchCatalogError("search channel")


@dataclass(frozen=True)
class SearchGap:
    """One place the keyword search could not read a vector or a graph."""

    jurisdiction: str
    admin_level: str
    instrument_kind: str
    reason: str
    corpus_id: str | None = None
    hf_repo: str | None = None


@dataclass(frozen=True)
class LegalTextSearch:
    """Hits and gaps for one keyword query."""

    query: str
    hits: tuple[SearchHit, ...]
    gaps: tuple[SearchGap, ...]
    research_only: bool = True
    authoritative: bool = False
    ducklake_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative or self.ducklake_authoritative or not self.research_only:
            raise LegalSearchCatalogError("search pin must stay observational")


@dataclass(frozen=True)
class CoverageCell:
    """One instrument, level, and jurisdiction in the corpus matrix."""

    jurisdiction: str
    admin_level: str
    instrument_kind: str
    reason: str
    hf_repo: str | None = None
    corpus_id: str | None = None


@dataclass(frozen=True)
class CorpusGapSample:
    """A seeded sample of cells that still need a scraper or an index."""

    gaps: tuple[CoverageCell, ...]
    population: int
    gap_population: int
    by_reason: tuple[tuple[str, int], ...]
    seed: int


def hash_embed(text: str, dims: int = 32) -> tuple[float, ...]:
    """Unit vector whose buckets follow the query's keyword hashes."""

    width = int(dims)
    if width < 1:
        raise LegalSearchCatalogError("embedding width")
    coordinates = [0.0] * width
    for token in str(text or "").casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % width
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        coordinates[bucket] += sign
    norm = math.sqrt(sum(value * value for value in coordinates))
    if norm == 0.0:
        return tuple(coordinates)
    return tuple(value / norm for value in coordinates)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return float(sum(a * b for a, b in zip(left, right)))


def _families(item: DatasetSchema) -> frozenset[str]:
    return frozenset(field.family for field in item.fields)


def _jurisdiction_keys(schemas: Sequence[DatasetSchema]) -> tuple[str, ...]:
    """Country keys, ``US``, and ``world``. Aliases share one key."""

    found = {"US", "world"}
    for item in schemas:
        if not item.corpus_id.startswith("country:"):
            continue
        slug = item.corpus_id[len("country:") :].split(":", 1)[0]
        key = _canonical_jurisdiction_key(slug)
        if key:
            found.add(key)
    return tuple(sorted(found))


def known_jurisdictions(
    releases: Sequence[CorpusRelease] | None = None,
) -> tuple[str, ...]:
    """Country slugs, ``US``, and ``world`` that the schema can name."""

    return _jurisdiction_keys(_schemas(releases))


def _schemas(
    releases: Sequence[CorpusRelease] | None,
) -> tuple[DatasetSchema, ...]:
    from ipfs_datasets_py.ducklake.legal_dataset_schema import _memory_schema

    chosen = legal_dataset_schema() if releases is None else tuple(releases)
    return _memory_schema(chosen)


def _cell_datasets(
    schemas: Sequence[DatasetSchema],
    *,
    jurisdiction: str,
    admin_level: str,
    instrument_kind: str,
) -> tuple[DatasetSchema, ...]:
    matched = [
        item
        for item in schemas
        if item.layout_profile != "excluded"
        and item.instrument_kind == instrument_kind
        and _matches_jurisdiction(item.corpus_id, jurisdiction)
        and _level_matches(item.corpus_id, item.instrument_kind, admin_level)
    ]
    return tuple(matched)


def _cell_reason(
    datasets: Sequence[DatasetSchema],
) -> tuple[str, DatasetSchema | None]:
    if not datasets:
        return "missing_corpus", None

    def ready(item: DatasetSchema) -> bool:
        families = _families(item)
        return (
            item.selected
            and item.searchable
            and "vectors" in families
            and ("graph_edges" in families or "graph_nodes" in families)
        )

    searchable = [item for item in datasets if ready(item)]
    if searchable:
        return "searchable_layout", searchable[0]
    selected = [item for item in datasets if item.selected and item.searchable]
    if selected:
        families = _families(selected[0])
        if "vectors" not in families:
            return "no_vector_layout", selected[0]
        return "no_graph_layout", selected[0]
    unverified = [item for item in datasets if item.layout_profile == "unverified"]
    if unverified:
        return "unverified", unverified[0]
    return "not_selected", datasets[0]


def coverage_matrix(
    releases: Sequence[CorpusRelease] | None = None,
) -> tuple[CoverageCell, ...]:
    """Every instrument, level, and known jurisdiction, with a gap reason."""

    schemas = _schemas(releases)
    cells: list[CoverageCell] = []
    for jurisdiction in _jurisdiction_keys(schemas):
        for admin_level in _LEVELS:
            for instrument_kind in _INSTRUMENTS:
                datasets = _cell_datasets(
                    schemas,
                    jurisdiction=jurisdiction,
                    admin_level=admin_level,
                    instrument_kind=instrument_kind,
                )
                reason, example = _cell_reason(datasets)
                cells.append(
                    CoverageCell(
                        jurisdiction=jurisdiction,
                        admin_level=admin_level,
                        instrument_kind=instrument_kind,
                        reason=reason,
                        hf_repo=None if example is None else example.hf_repo,
                        corpus_id=None if example is None else example.corpus_id,
                    )
                )
    return tuple(cells)


def sample_corpus_gaps(
    *,
    limit: int = 48,
    seed: int = 0,
    releases: Sequence[CorpusRelease] | None = None,
) -> CorpusGapSample:
    """Sample gap cells across instrument, level, and jurisdiction.

    ``searchable_layout`` cells are omitted. The sample is seeded and
    round-robin across instrument and level so a short sample still spans
    the axes a scraper run has to cover.
    """

    matrix = coverage_matrix(releases)
    counts: dict[str, int] = {}
    gaps: list[CoverageCell] = []
    for cell in matrix:
        counts[cell.reason] = counts.get(cell.reason, 0) + 1
        if cell.reason != "searchable_layout":
            gaps.append(cell)
    buckets: dict[tuple[str, str], list[CoverageCell]] = {}
    for cell in gaps:
        buckets.setdefault((cell.instrument_kind, cell.admin_level), []).append(cell)
    rng = random.Random(seed)
    keys = list(buckets)
    rng.shuffle(keys)
    for rows in buckets.values():
        rng.shuffle(rows)
    picked: list[CoverageCell] = []
    target = max(0, int(limit))
    while len(picked) < target:
        progressed = False
        for key in keys:
            rows = buckets[key]
            if not rows:
                continue
            picked.append(rows.pop())
            progressed = True
            if len(picked) >= target:
                break
        if not progressed:
            break
    return CorpusGapSample(
        gaps=tuple(picked),
        population=len(matrix),
        gap_population=len(gaps),
        by_reason=tuple(sorted(counts.items())),
        seed=seed,
    )


# Levels at which that instrument is actually issued. A county patent is a
# matrix cell, not a scraper job. County ordinances reuse the municipal corpus.
_EXPECTED_LEVELS = {
    "patent": frozenset({"national"}),
    "register": frozenset({"national"}),
    "form": frozenset({"national"}),
    "order": frozenset({"national", "state"}),
    "ordinance": frozenset({"municipal", "county"}),
    "case": frozenset({"national", "state"}),
    "court": frozenset({"national", "state"}),
    "rule": frozenset({"national", "state"}),
    "regulation": frozenset({"national", "state"}),
    "statute": frozenset({"national", "state"}),
}
_PARTITION_SUFFIXES = (
    "_state",
    "_provincial",
    "_regional",
    "_district",
    "_county",
    "_governorate",
)
_NO_MUNICIPAL_JURISDICTION = frozenset({"eu", "world"})
# Selected text packs we should not embed until someone checks that the
# rows are a real, non-duplicate law set.
_INDEX_HOLD_CORPORA = frozenset({
    "country:antarctica",
    "country:bouvetisland",
    "country:britishindianoceanterritory",
    "country:france_local",
    "country:frenchsouthernterritories",
    "country:heardislandandmcdonaldislands",
    "country:indonesia_east_java",
    "country:italy_regional",
    "country:puertorico",
    "country:runion",
    "country:saintbarthlemy",
    "country:saintmartinfrenchpart",
    "country:southgeorgiaandthesouthsandwichislands",
    "country:unitedstatesminoroutlyingislands",
    "country:us_local",
    "world:scanned-text",
})
# Selected packs that must not be built and uploaded.
# Tokelau's own card says the source is all rights reserved.
# Western Sahara ships provenance scripts and no laws.parquet.
# American Samoa's license field says to verify territorial reuse terms.
_PUBLISH_HOLDS = {
    "endomorphosis/ipfs_tokelau_laws": (
        "review_rights",
        "HOLD_RIGHTS_UNRESOLVED.md says all rights reserved. Do not upload an index.",
    ),
    "endomorphosis/ipfs_americansamoa_laws": (
        "review_rights",
        "License field says attribution is required and territorial reuse terms must be verified. Do not upload an index yet.",
    ),
    "endomorphosis/ipfs_macao_laws": (
        "review_rights",
        "License field names the official gazette and attribution, and does not grant redistribution. Do not upload an index yet.",
    ),
    "endomorphosis/ipfs_westernsahara_laws": (
        "review_pack",
        "Provenance scripts only. There is no laws.parquet to index.",
    ),
}
# Missing packs worth a source search because a sibling instrument is already published.
_SOURCE_CHECKS = (
    ("czechia", "case", "national", "Czechia already has a regulation corpus."),
    ("india", "court", "national", "India already has caselaw."),
    ("india", "regulation", "national", "India already has caselaw."),
    ("ireland", "case", "national", "Ireland already has a court directory."),
    ("japan", "case", "national", "Japan already has a regulation corpus."),
    ("malawi", "court", "national", "Malawi already has caselaw."),
    ("malawi", "regulation", "national", "Malawi already has caselaw."),
    ("netherlands", "regulation", "national", "The Netherlands already has caselaw and a court directory."),
    ("newzealand", "case", "national", "New Zealand already has a court directory."),
    ("poland", "court", "national", "Poland already has caselaw and regulations."),
    ("southafrica", "court", "national", "South Africa already has caselaw."),
    ("southafrica", "regulation", "national", "South Africa already has caselaw."),
    ("spain", "case", "national", "Spain already has regulations and a subnational statute pack."),
    ("switzerland", "court", "national", "Switzerland already has caselaw."),
    ("switzerland", "regulation", "national", "Switzerland already has caselaw."),
    ("uk", "case", "national", "The UK already has regulations and a court directory."),
)
_PIN_LAYOUTS = frozenset({"world-law/v1.1.0", "legal-record/v1"})
# Source repositories the index publisher must not overwrite. An ``_ir``
# sibling is a different repo and is allowed.
_PROTECTED_PUBLISH_REPOS = frozenset({
    "justicedao/ipfs_state_laws",
    "justicedao/ipfs_federal_register",
})


def justicedao_index_repo(source_repo: str) -> str:
    """Return the JusticeDAO dataset that should receive this corpus's index.

    The source may be ``endomorphosis/ipfs_<slug>_laws`` or an existing
    ``justicedao`` text pack. The index is ``justicedao/<leaf>_ir``. A leaf
    that already ends in ``_ir`` or ``-ir`` is not suffixed again. An empty
    name is refused. The protected US state-law and Federal Register
    repositories are never returned.
    """

    raw = str(source_repo or "").strip()
    if not raw or raw in {"/", "."} or raw.endswith("/"):
        raise LegalSearchCatalogError("index publish repo needs a dataset name")
    leaf = raw.strip("/").rsplit("/", 1)[-1].strip()
    if not leaf or leaf in {".", ".."} or "/" in leaf:
        raise LegalSearchCatalogError("index publish repo needs a dataset name")
    folded = leaf.casefold()
    if folded.endswith("_ir") or folded.endswith("-ir"):
        name = leaf
    else:
        name = f"{leaf}_ir"
    repo = f"justicedao/{name}"
    if repo in _PROTECTED_PUBLISH_REPOS:
        raise LegalSearchCatalogError(
            f"{repo} is a protected JusticeDAO repository; publish the index as a different repo"
        )
    return repo


def _index_job_detail(hf_repo: str, publish_repo: str, instrument_kind: str, admin_level: str) -> str:
    leaf = hf_repo.rsplit("/", 1)[-1]
    if (
        instrument_kind == "statute"
        and admin_level == "national"
        and leaf.startswith("ipfs_")
        and leaf.endswith("_laws")
    ):
        return (
            "Selected statute pack. Build with country_laws_ir and --upload. "
            f"The only publish target is {publish_repo}."
        )
    return (
        "Selected corpus has no vector family. "
        f"The only publish target is {publish_repo}. "
        "Do not send this pack through the country-laws statute builder."
    )


@dataclass(frozen=True)
class CorpusWorkItem:
    """One gap that is either work to queue or a check before any scraper runs."""

    disposition: str
    action: str
    instrument_kind: str
    admin_level: str
    jurisdiction: str
    hf_repo: str | None = None
    corpus_id: str | None = None
    detail: str = ""
    publish_repo: str | None = None


@dataclass(frozen=True)
class CorpusWorkTodo:
    """The scraper queue, the checks, and the cells that are not laws."""

    queue: tuple[CorpusWorkItem, ...]
    double_check: tuple[CorpusWorkItem, ...]
    not_expected: tuple[tuple[str, str, int], ...]
    population: int


def _is_partition_key(jurisdiction: str) -> bool:
    return jurisdiction.endswith(_PARTITION_SUFFIXES)


def _work_sort(item: CorpusWorkItem) -> tuple[str, str, str, str]:
    return (item.action, item.jurisdiction, item.instrument_kind, item.hf_repo or "")


def corpus_work_todo(
    releases: Sequence[CorpusRelease] | None = None,
) -> CorpusWorkTodo:
    """Split the coverage matrix into queued work, checks, and non-laws.

    A county patent is ``not_expected``. A selected corpus with no vector
    family is an index job, unless the corpus is on the hold list. A
    country with a searchable national statute layout and no municipal
    ordinance corpus is an ordinance scrape. County rows are not a second
    scrape. The raw ``sample_corpus_gaps`` draw is unchanged.
    """

    schemas = _schemas(releases)
    matrix = coverage_matrix(releases)
    by_cell = {
        (cell.jurisdiction, cell.admin_level, cell.instrument_kind): cell
        for cell in matrix
    }
    statute_ready = {
        cell.jurisdiction
        for cell in matrix
        if cell.instrument_kind == "statute"
        and cell.admin_level == "national"
        and cell.reason == "searchable_layout"
    }
    queue: list[CorpusWorkItem] = []
    double_check: list[CorpusWorkItem] = []
    unexpected: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, str]] = set()

    def add(bucket: list[CorpusWorkItem], item: CorpusWorkItem) -> None:
        key = (item.action, item.corpus_id or item.jurisdiction, item.hf_repo or item.instrument_kind)
        if key in seen:
            return
        seen.add(key)
        bucket.append(item)

    for item in schemas:
        if item.layout_profile in {"excluded", "unclassified"}:
            continue
        if item.layout_profile == "unverified":
            add(
                double_check,
                CorpusWorkItem(
                    disposition="double_check",
                    action="verify_layout",
                    instrument_kind=item.instrument_kind,
                    admin_level=corpus_admin_level(item.corpus_id, item.instrument_kind),
                    jurisdiction=_corpus_jurisdiction_key(item.corpus_id) or "US",
                    hf_repo=item.hf_repo,
                    corpus_id=item.corpus_id,
                    detail="Layout is unverified. Read the files before indexing. Leave it unselected.",
                ),
            )
            continue
        if item.layout_profile in _PIN_LAYOUTS and not item.selected:
            add(
                double_check,
                CorpusWorkItem(
                    disposition="double_check",
                    action="pin_review",
                    instrument_kind=item.instrument_kind,
                    admin_level=corpus_admin_level(item.corpus_id, item.instrument_kind),
                    jurisdiction=_corpus_jurisdiction_key(item.corpus_id) or "world",
                    hf_repo=item.hf_repo,
                    corpus_id=item.corpus_id,
                    detail="Pin-gated. Do not select this repo to close a gap.",
                ),
            )
            continue
        if not item.selected or not item.searchable:
            continue
        families = _families(item)
        has_vectors = "vectors" in families
        has_graph = "graph_edges" in families or "graph_nodes" in families
        if has_vectors and has_graph:
            continue
        level = corpus_admin_level(item.corpus_id, item.instrument_kind)
        if level == "judicial":
            level = "national"
        jurisdiction = _corpus_jurisdiction_key(item.corpus_id) or "any"
        if has_vectors and not has_graph:
            add(
                double_check,
                CorpusWorkItem(
                    disposition="double_check",
                    action="review_graph",
                    instrument_kind=item.instrument_kind,
                    admin_level=level,
                    jurisdiction=jurisdiction,
                    hf_repo=item.hf_repo,
                    corpus_id=item.corpus_id,
                    detail="Vectors are already declared and a graph family is not. Confirm this is not a sibling of a corpus that already has both.",
                ),
            )
            continue
        if item.corpus_id in _INDEX_HOLD_CORPORA:
            add(
                double_check,
                CorpusWorkItem(
                    disposition="double_check",
                    action="review_pack",
                    instrument_kind=item.instrument_kind,
                    admin_level=level,
                    jurisdiction=jurisdiction,
                    hf_repo=item.hf_repo,
                    corpus_id=item.corpus_id,
                    detail="Selected text pack. Confirm it is non-empty and not a duplicate spelling before embedding.",
                ),
            )
            continue
        sibling_ready = any(
            cell.reason == "searchable_layout"
            and cell.jurisdiction == jurisdiction
            and cell.instrument_kind == item.instrument_kind
            and cell.admin_level == level
            for cell in matrix
        )
        if sibling_ready:
            add(
                double_check,
                CorpusWorkItem(
                    disposition="double_check",
                    action="review_overlap",
                    instrument_kind=item.instrument_kind,
                    admin_level=level,
                    jurisdiction=jurisdiction,
                    hf_repo=item.hf_repo,
                    corpus_id=item.corpus_id,
                    detail="Another selected corpus for this jurisdiction and instrument already declares vectors and a graph.",
                ),
            )
            continue
        if not item.hf_repo:
            raise LegalSearchCatalogError(f"index job {item.corpus_id} has no source repo")
        publish_hold = _PUBLISH_HOLDS.get(item.hf_repo)
        if publish_hold:
            action, detail = publish_hold
            add(
                double_check,
                CorpusWorkItem(
                    disposition="double_check",
                    action=action,
                    instrument_kind=item.instrument_kind,
                    admin_level=level,
                    jurisdiction=jurisdiction,
                    hf_repo=item.hf_repo,
                    corpus_id=item.corpus_id,
                    detail=detail,
                ),
            )
            continue
        publish_repo = justicedao_index_repo(item.hf_repo)
        add(
            queue,
            CorpusWorkItem(
                disposition="queue",
                action="index",
                instrument_kind=item.instrument_kind,
                admin_level=level,
                jurisdiction=jurisdiction,
                hf_repo=item.hf_repo,
                corpus_id=item.corpus_id,
                publish_repo=publish_repo,
                detail=_index_job_detail(item.hf_repo, publish_repo, item.instrument_kind, level),
            ),
        )

    for cell in matrix:
        expected = _EXPECTED_LEVELS.get(cell.instrument_kind, frozenset())
        if cell.admin_level not in expected:
            key = (cell.instrument_kind, cell.admin_level)
            unexpected[key] = unexpected.get(key, 0) + 1
            continue
        if cell.instrument_kind == "ordinance" and cell.admin_level == "county":
            continue
        if cell.reason != "missing_corpus":
            continue
        if (
            cell.instrument_kind == "ordinance"
            and cell.admin_level == "municipal"
            and cell.jurisdiction in statute_ready
            and cell.jurisdiction not in _NO_MUNICIPAL_JURISDICTION
            and not _is_partition_key(cell.jurisdiction)
        ):
            add(
                queue,
                CorpusWorkItem(
                    disposition="queue",
                    action="scrape_ordinances",
                    instrument_kind="ordinance",
                    admin_level="municipal",
                    jurisdiction=cell.jurisdiction,
                    detail="National statute layout is searchable. Confirm a municipal code, then scrape it. County search uses that corpus.",
                ),
            )

    for jurisdiction, kind, level, detail in _SOURCE_CHECKS:
        cell = by_cell.get((jurisdiction, level, kind))
        if cell is None or cell.reason != "missing_corpus":
            continue
        add(
            queue,
            CorpusWorkItem(
                disposition="queue",
                action="source_check",
                instrument_kind=kind,
                admin_level=level,
                jurisdiction=jurisdiction,
                detail=detail + " Find the public source before scraping.",
            ),
        )

    partitions = sorted(
        jurisdiction
        for jurisdiction in statute_ready
        if _is_partition_key(jurisdiction)
    )
    if partitions:
        add(
            double_check,
            CorpusWorkItem(
                disposition="double_check",
                action="review_partition",
                instrument_kind="statute",
                admin_level="national",
                jurisdiction="partitions",
                detail="These keys are subnational partitions with their own statute layout, not extra countries: "
                + ", ".join(partitions)
                + ". Do not queue a separate municipal scraper for each one.",
            ),
        )
    return CorpusWorkTodo(
        queue=tuple(sorted(queue, key=_work_sort)),
        double_check=tuple(sorted(double_check, key=_work_sort)),
        not_expected=tuple(
            (kind, level, count)
            for (kind, level), count in sorted(unexpected.items())
        ),
        population=len(matrix),
    )


def _scope_label(
    *,
    jurisdiction: str | None,
    admin_level: str | None,
    instrument_kind: str | None,
    item: DatasetSchema | None,
) -> tuple[str, str, str]:
    level = admin_level or ("" if item is None else corpus_admin_level(item.corpus_id, item.instrument_kind))
    if level == "judicial":
        level = "national"
    kind = instrument_kind or ("" if item is None else item.instrument_kind)
    place = jurisdiction or "any"
    return place, level, kind


def search_legal_text(
    query: str,
    *,
    jurisdiction: str | None = None,
    corpus_id: str | None = None,
    hf_repo: str | None = None,
    instrument_kind: str | None = None,
    admin_level: str | None = None,
    latitude: str | float | None = None,
    longitude: str | float | None = None,
    limit: int = 10,
    embed: Callable[[str], Sequence[float]] | None = None,
    vector_rows: Iterable[VectorProbe] = (),
    graph_edges: Iterable[GraphEdge] = (),
    connection=None,
    releases: Sequence[CorpusRelease] | None = None,
) -> LegalTextSearch:
    """Search loaded vectors, then walk one graph hop from those hits.

    The same filters as ``request_legal_data`` choose the corpora. A corpus
    with no probe is a gap, not a silent miss. Hits carry entry ids and
    scores only.
    """

    text = " ".join(str(query or "").split())
    if not text:
        raise LegalSearchCatalogError("query")
    bounded = int(limit)
    if bounded < 1:
        raise LegalSearchCatalogError("limit")
    encoder = hash_embed if embed is None else embed
    query_vector = tuple(float(value) for value in encoder(text))
    probes: dict[str, list[VectorProbe]] = {}
    for row in vector_rows:
        probes.setdefault(row.corpus_id, []).append(row)
    edges: dict[tuple[str, str], list[GraphEdge]] = {}
    for edge in graph_edges:
        edges.setdefault((edge.corpus_id, edge.source_cid), []).append(edge)

    located = request_legal_data(
        jurisdiction=jurisdiction,
        corpus_id=corpus_id,
        hf_repo=hf_repo,
        instrument_kind=instrument_kind,
        admin_level=admin_level,
        latitude=latitude,
        longitude=longitude,
        connection=connection,
        releases=releases,
    )
    place = jurisdiction or (
        located.place.country_code if located.place is not None and located.place.country_code else None
    )
    if not located.datasets:
        gap_place, gap_level, gap_kind = _scope_label(
            jurisdiction=place,
            admin_level=admin_level,
            instrument_kind=instrument_kind,
            item=None,
        )
        return LegalTextSearch(
            query=text,
            hits=(),
            gaps=(
                SearchGap(
                    jurisdiction=gap_place,
                    admin_level=gap_level or (admin_level or "any"),
                    instrument_kind=gap_kind or (instrument_kind or "any"),
                    reason="missing_corpus",
                ),
            ),
        )

    hits: list[SearchHit] = []
    gaps: list[SearchGap] = []
    for item in located.datasets:
        families = _families(item)
        level = corpus_admin_level(item.corpus_id, item.instrument_kind)
        if level == "judicial":
            level = admin_level or "national"
        label = (
            place or "any",
            admin_level or level,
            instrument_kind or item.instrument_kind,
        )
        ranked: list[tuple[float, VectorProbe]] = []
        available = probes.get(item.corpus_id, [])
        if available:
            for probe in available:
                ranked.append((_cosine(query_vector, probe.coordinates), probe))
            ranked.sort(key=lambda pair: (-pair[0], pair[1].entry_cid))
        elif "vectors" not in families:
            gaps.append(SearchGap(*label, "no_vector_layout", item.corpus_id, item.hf_repo))
        else:
            gaps.append(SearchGap(*label, "vector_index_not_loaded", item.corpus_id, item.hf_repo))
        seen: set[str] = set()
        for score, probe in ranked[:bounded]:
            seen.add(probe.entry_cid)
            hits.append(
                SearchHit(
                    corpus_id=item.corpus_id,
                    hf_repo=item.hf_repo,
                    entry_cid=probe.entry_cid,
                    instrument_kind=item.instrument_kind,
                    admin_level=label[1],
                    channel="vector",
                    score=score,
                )
            )
        walked = False
        for score, probe in ranked[:bounded]:
            for edge in edges.get((item.corpus_id, probe.entry_cid), []):
                if edge.target_cid in seen:
                    continue
                seen.add(edge.target_cid)
                walked = True
                hits.append(
                    SearchHit(
                        corpus_id=item.corpus_id,
                        hf_repo=item.hf_repo,
                        entry_cid=edge.target_cid,
                        instrument_kind=item.instrument_kind,
                        admin_level=label[1],
                        channel="graph",
                        score=score * _GRAPH_HOP,
                        relation=edge.relation,
                    )
                )
        has_graph_layout = "graph_edges" in families or "graph_nodes" in families
        has_graph_index = any(key[0] == item.corpus_id for key in edges)
        if not walked and not has_graph_index:
            reason = "no_graph_layout" if not has_graph_layout else "graph_index_not_loaded"
            gaps.append(SearchGap(*label, reason, item.corpus_id, item.hf_repo))
    hits.sort(key=lambda hit: (-hit.score, hit.channel, hit.corpus_id, hit.entry_cid))
    return LegalTextSearch(query=text, hits=tuple(hits[:bounded]), gaps=tuple(gaps))
