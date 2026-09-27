"""One search pin per JusticeDAO legal source.

Name classification only. It does not download parquet, read a README, or
open DuckDB. A later profile check can replace a pin; this module only
stops duplicate repos from being searched as if they were different laws.

The lake that consumes these rows is observational. Official sources stay
the authority. ``authoritative`` and ``ducklake_authoritative`` stay false.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence

_REPO = re.compile(r"^(?:justicedao/)?(?P<name>[A-Za-z0-9_.-]+)$")
_COUNTRY_IR = re.compile(r"^ipfs_(?P<slug>[a-z0-9_]+)_laws(?P<suffix>_ir|-ir)?$")

_EXCLUDED = frozenset({"legal-ir-autoencoder-checkpoints"})
_CASELAW_TEXT = frozenset({"ipfs_caselaw_access_project"})
_CASELAW_ALTERNATE = frozenset({"dedup_ipfs_caselaw_access_project"})
_CASELAW_EMBEDDINGS = frozenset({
    "Caselaw_Access_Project_embeddings",
    "caselaw_access_project_embeddings",
})
_PATENT_PIN = "patent-legal-ir-graphrag"
_PATENT_SPLITS = frozenset({
    "patent-legal-corpus",
    "patent-legal-bm25",
    "patent-legal-vectors",
    "patent-legal-knowledge-graph",
})
_FEDERAL_PIN = "federal-register-full-graphrag-v20260810"
_FEDERAL_RESEARCH = frozenset({
    "ipfs_federal_register",
    "federal-register-live-graphrag-research-20260810",
})
_NETHERLANDS_CAPPED = frozenset({
    "ipfs_netherlands_laws",
    "ipfs_netherlands_laws_bm25_index",
    "ipfs_netherlands_laws_vector_index",
    "ipfs_netherlands_laws_knowledge_graph",
    "wetwijzer_netherlands_legal_corpus",
    "netherlands-laws-nl-normalized",
})
_UNVERIFIED = frozenset({"ipfs_court_rules", "ipfs_state_admin_rules"})

_LAYOUTS = frozenset({
    "country-laws-ir-graphrag/v1",
    "publicus-ir-graphrag/v2",
    "patent-legal-ir-graphrag",
    "legacy-split",
    "municipal-gnis",
    "caselaw-text",
    "caselaw-embeddings",
    "unverified",
    "excluded",
    "unclassified",
})


@dataclass(frozen=True)
class CorpusRelease:
    """One Hugging Face repo after duplicate repos collapse to one source."""

    corpus_id: str
    hf_repo: str
    layout_profile: str
    coverage: str
    primary_key: str
    instrument_kind: str
    selected: bool
    searchable: bool
    text_corpus: bool
    supersedes: tuple[str, ...] = ()
    research_only: bool = True
    authoritative: bool = False
    ducklake_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.layout_profile not in _LAYOUTS:
            raise ValueError(f"unknown layout profile: {self.layout_profile}")
        if self.authoritative or self.ducklake_authoritative:
            raise ValueError("a legal search pin cannot claim authority")
        if not self.research_only:
            raise ValueError("a legal search pin is research-only")


def _repo_name(dataset_id: str) -> str:
    match = _REPO.fullmatch(str(dataset_id or "").strip())
    if match is None:
        raise ValueError(f"not a JusticeDAO dataset id: {dataset_id!r}")
    return match.group("name")


def _full_id(name: str) -> str:
    return f"justicedao/{name}"


def _row(**kwargs: object) -> CorpusRelease:
    return CorpusRelease(**kwargs)  # type: ignore[arg-type]


def _classify_one(name: str) -> CorpusRelease:
    repo = _full_id(name)
    if name in _EXCLUDED:
        return _row(
            corpus_id="artifact:legal-ir-autoencoder",
            hf_repo=repo,
            layout_profile="excluded",
            coverage="excluded",
            primary_key="",
            instrument_kind="excluded",
            selected=False,
            searchable=False,
            text_corpus=False,
        )
    if name in _CASELAW_EMBEDDINGS:
        return _row(
            corpus_id="us:caselaw-embeddings",
            hf_repo=repo,
            layout_profile="caselaw-embeddings",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="case",
            selected=True,
            searchable=True,
            text_corpus=False,
        )
    if name in _CASELAW_TEXT or name in _CASELAW_ALTERNATE:
        return _row(
            corpus_id="us:caselaw",
            hf_repo=repo,
            layout_profile="caselaw-text",
            coverage="snapshot",
            primary_key="id",
            instrument_kind="case",
            selected=name in _CASELAW_TEXT,
            searchable=name in _CASELAW_TEXT,
            text_corpus=True,
        )
    if name == "american_municipal_law":
        return _row(
            corpus_id="us:municipal",
            hf_repo=repo,
            layout_profile="municipal-gnis",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="municipal",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_uscode":
        return _row(
            corpus_id="us:code",
            hf_repo=repo,
            layout_profile="publicus-ir-graphrag/v2",
            coverage="current-bundle",
            primary_key="entry_cid",
            instrument_kind="statute",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_state_laws":
        return _row(
            corpus_id="us:state-statutes",
            hf_repo=repo,
            layout_profile="publicus-ir-graphrag/v2",
            coverage="current-bundle",
            primary_key="entry_cid",
            instrument_kind="statute",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "open-us-law-sparse-graphrag":
        return _row(
            corpus_id="us:open-us-law",
            hf_repo=repo,
            layout_profile="publicus-ir-graphrag/v2",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="statute",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == _FEDERAL_PIN or name in _FEDERAL_RESEARCH:
        selected = name == _FEDERAL_PIN
        return _row(
            corpus_id="us:federal-register",
            hf_repo=repo,
            layout_profile="publicus-ir-graphrag/v2",
            coverage="current-bundle" if selected else "research",
            primary_key="entry_cid",
            instrument_kind="register",
            selected=selected,
            searchable=selected,
            text_corpus=True,
        )
    if name == _PATENT_PIN or name in _PATENT_SPLITS:
        selected = name == _PATENT_PIN
        return _row(
            corpus_id="us:patent",
            hf_repo=repo,
            layout_profile="patent-legal-ir-graphrag" if selected else "legacy-split",
            coverage="current-bundle" if selected else "snapshot",
            primary_key="entry_cid",
            instrument_kind="patent",
            selected=selected,
            searchable=selected,
            text_corpus=True,
        )
    if name in _UNVERIFIED:
        return _row(
            corpus_id=f"us:{name.removeprefix('ipfs_').replace('_', '-')}",
            hf_repo=repo,
            layout_profile="unverified",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="rule",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name in _NETHERLANDS_CAPPED:
        return _row(
            corpus_id="country:netherlands",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="capped",
            primary_key="cid",
            instrument_kind="statute",
            selected=False,
            searchable=False,
            text_corpus=name == "ipfs_netherlands_laws",
        )
    match = _COUNTRY_IR.fullmatch(name)
    if match is not None:
        slug = match.group("slug")
        suffix = match.group("suffix") or ""
        underscore = suffix == "_ir"
        hyphen = suffix == "-ir"
        selected = underscore or suffix == ""
        if hyphen:
            selected = False
        return _row(
            corpus_id=f"country:{slug}",
            hf_repo=repo,
            layout_profile="country-laws-ir-graphrag/v1" if suffix else "legacy-split",
            coverage="snapshot" if suffix else "capped",
            primary_key="entry_cid" if suffix else "cid",
            instrument_kind="statute",
            selected=selected and bool(suffix),
            searchable=selected and bool(suffix),
            text_corpus=True,
        )
    return _row(
        corpus_id=f"unclassified:{name}",
        hf_repo=repo,
        layout_profile="unclassified",
        coverage="snapshot",
        primary_key="",
        instrument_kind="unclassified",
        selected=False,
        searchable=False,
        text_corpus=False,
    )


def _prefer(candidate: CorpusRelease, challenger: CorpusRelease) -> CorpusRelease:
    """Pick the repo that should be searched for one source."""

    rank = {
        "country-laws-ir-graphrag/v1": 0,
        "publicus-ir-graphrag/v2": 0,
        "patent-legal-ir-graphrag": 0,
        "caselaw-text": 1,
        "caselaw-embeddings": 1,
        "municipal-gnis": 1,
        "legacy-split": 3,
        "unverified": 4,
        "excluded": 5,
        "unclassified": 6,
    }
    if rank[challenger.layout_profile] < rank[candidate.layout_profile]:
        return challenger
    if rank[challenger.layout_profile] > rank[candidate.layout_profile]:
        return candidate
    if challenger.hf_repo.endswith("_laws_ir") and not candidate.hf_repo.endswith("_laws_ir"):
        return challenger
    if candidate.hf_repo.endswith("_laws_ir") and not challenger.hf_repo.endswith("_laws_ir"):
        return candidate
    if challenger.coverage == "current-bundle" and candidate.coverage != "current-bundle":
        return challenger
    if candidate.coverage == "current-bundle" and challenger.coverage != "current-bundle":
        return candidate
    if challenger.hf_repo.endswith("/ipfs_caselaw_access_project"):
        return challenger
    if candidate.hf_repo.endswith("/ipfs_caselaw_access_project"):
        return candidate
    return candidate


def build_release_registry(dataset_ids: Iterable[str]) -> tuple[CorpusRelease, ...]:
    """Collapse a Hugging Face id list to one selected pin per legal source.

    Every input id is returned. Repos that lose the pin stay in the tuple
    with ``selected=False`` and are named by the winner's ``supersedes``.
    """

    classified: list[CorpusRelease] = []
    seen: set[str] = set()
    for raw in dataset_ids:
        name = _repo_name(raw)
        repo = _full_id(name)
        if repo in seen:
            continue
        seen.add(repo)
        classified.append(_classify_one(name))

    grouped: dict[str, list[CorpusRelease]] = {}
    for item in classified:
        grouped.setdefault(item.corpus_id, []).append(item)

    chosen: dict[str, str] = {}
    for corpus_id, items in grouped.items():
        winner = items[0]
        for item in items[1:]:
            winner = _prefer(winner, item)
        chosen[corpus_id] = winner.hf_repo

    resolved: list[CorpusRelease] = []
    for item in classified:
        winner = chosen[item.corpus_id]
        selected = item.hf_repo == winner and item.layout_profile != "excluded"
        others = tuple(
            sorted(
                sibling.hf_repo
                for sibling in grouped[item.corpus_id]
                if sibling.hf_repo != item.hf_repo
            )
        )
        if item.layout_profile == "caselaw-embeddings":
            selected = True
        if item.layout_profile == "unverified":
            selected = False
        searchable = selected and item.layout_profile != "excluded"
        if item.layout_profile == "caselaw-text" and item.hf_repo != winner:
            selected = False
            searchable = False
        resolved.append(
            CorpusRelease(
                corpus_id=item.corpus_id,
                hf_repo=item.hf_repo,
                layout_profile=item.layout_profile,
                coverage=item.coverage,
                primary_key=item.primary_key,
                instrument_kind=item.instrument_kind,
                selected=selected,
                searchable=searchable,
                text_corpus=item.text_corpus,
                supersedes=others if selected else (),
            )
        )
    return tuple(sorted(resolved, key=lambda item: (item.corpus_id, item.hf_repo)))


def selected_releases(releases: Sequence[CorpusRelease]) -> tuple[CorpusRelease, ...]:
    """Pins that default search is allowed to open."""

    return tuple(item for item in releases if item.selected and item.searchable)
