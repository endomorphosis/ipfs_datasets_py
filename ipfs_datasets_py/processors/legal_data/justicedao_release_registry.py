"""One search pin per JusticeDAO or endomorphosis legal source.

Name classification only. It does not download parquet, read a README, or
open DuckDB. A later profile check can replace a pin; this module only
stops duplicate repos from being searched as if they were different laws.

Bare dataset names stay ``justicedao/`` names. ``endomorphosis/`` ids keep
that org. The lake that consumes these rows is observational. Official
sources stay the authority. ``authoritative`` and ``ducklake_authoritative``
stay false.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence

from ipfs_datasets_py.processors.legal_data.justicedao_release_pins import pin_readable

_ORGS = frozenset({"justicedao", "endomorphosis"})
_REPO = re.compile(
    r"^(?:(?P<org>justicedao|endomorphosis)/)?(?P<name>[A-Za-z0-9_.-]+)$"
)
_COUNTRY_IR = re.compile(r"^ipfs_(?P<slug>[a-z0-9_]+)_laws(?P<suffix>_ir|-ir)?$")
_LAWS_NORM = re.compile(r"^ipfs_(?P<slug>[a-z0-9_]+)_laws_norm$")
_LAWS_EXTRA = re.compile(
    r"^ipfs_(?P<slug>[a-z0-9_]+)_laws_(?P<extra>rc2|supplement)$"
)
_LOCAL_ACTS = re.compile(
    r"^ipfs_(?P<slug>[a-z0-9_]+)_local_acts(?P<suffix>_ir)?$"
)
_KIND = re.compile(
    r"^ipfs_(?P<slug>[a-z0-9_]+)_(?P<kind>caselaw|regulations|courts)$"
)
_PIN_GATED = frozenset({"world-law/v1.1.0", "legal-record/v1"})
_SLUG_ALIAS = {
    "unitedkingdom": "uk",
    "south_africa": "southafrica",
    "new_zealand": "newzealand",
}
_ARTIFACT_MARKERS = (
    "span-cache",
    "entity-cache",
    "autoencoder",
    "autoformal",
    "embeddings_test",
)
_ARTIFACT_NAMES = frozenset({
    "211-ai-artifacts",
    "211-info",
    "ipfs_legal_scrapers_and_normalizers",
})

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
    "caselaw-graphrag/v1",
    "world-law/v1.1.0",
    "legal-record/v1",
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


def _split_id(dataset_id: str) -> tuple[str, str]:
    match = _REPO.fullmatch(str(dataset_id or "").strip())
    if match is None:
        raise ValueError(f"not a legal dataset id: {dataset_id!r}")
    org = match.group("org") or "justicedao"
    if org not in _ORGS:
        raise ValueError(f"not a legal dataset id: {dataset_id!r}")
    return org, match.group("name")


def _full_id(org: str, name: str) -> str:
    return f"{org}/{name}"


def _canonical_slug(slug: str) -> str:
    return _SLUG_ALIAS.get(slug, slug)


def _row(**kwargs: object) -> CorpusRelease:
    return CorpusRelease(**kwargs)  # type: ignore[arg-type]


def _classify_one(name: str, org: str = "justicedao") -> CorpusRelease:
    repo = _full_id(org, name)
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
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "american_municipal_law_norm":
        return _row(
            corpus_id="us:municipal-norm",
            hf_repo=repo,
            layout_profile="legal-record/v1",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="ordinance",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "world_national_law":
        return _row(
            corpus_id="world:national",
            hf_repo=repo,
            layout_profile="world-law/v1.1.0",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="statute",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "world_municipal_law":
        return _row(
            corpus_id="world:municipal",
            hf_repo=repo,
            layout_profile="world-law/v1.1.0",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="ordinance",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "world_municipal_law_norm":
        return _row(
            corpus_id="world:municipal-norm",
            hf_repo=repo,
            layout_profile="legal-record/v1",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="ordinance",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "world_law_scrapers":
        return _row(
            corpus_id="artifact:world-law-scrapers",
            hf_repo=repo,
            layout_profile="excluded",
            coverage="excluded",
            primary_key="",
            instrument_kind="excluded",
            selected=False,
            searchable=False,
            text_corpus=False,
        )
    if name == "legal_scrapers":
        return _row(
            corpus_id="artifact:legal-scrapers",
            hf_repo=repo,
            layout_profile="excluded",
            coverage="excluded",
            primary_key="",
            instrument_kind="excluded",
            selected=False,
            searchable=False,
            text_corpus=False,
        )
    if name == "ipfs_state_laws_normalized_graphrag":
        return _row(
            corpus_id="us:state-statutes-normalized",
            hf_repo=repo,
            layout_profile="unclassified",
            coverage="snapshot",
            primary_key="",
            instrument_kind="unclassified",
            selected=False,
            searchable=False,
            text_corpus=False,
        )
    if name == "ipfs_american_municipal_law_normalized_graphrag":
        return _row(
            corpus_id="us:municipal-normalized",
            hf_repo=repo,
            layout_profile="unclassified",
            coverage="snapshot",
            primary_key="",
            instrument_kind="unclassified",
            selected=False,
            searchable=False,
            text_corpus=False,
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
        procedure = name == "ipfs_court_rules"
        return _row(
            corpus_id=f"us:{name.removeprefix('ipfs_').replace('_', '-')}",
            hf_repo=repo,
            layout_profile="unverified",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="rule" if procedure else "regulation",
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
    norm = _LAWS_NORM.fullmatch(name)
    if norm is not None:
        slug = norm.group("slug")
        return _row(
            corpus_id=f"country:{slug}",
            hf_repo=repo,
            layout_profile="legal-record/v1",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="ordinance" if "_municipal" in slug else "statute",
            selected=False,
            searchable=False,
            text_corpus=True,
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
            instrument_kind="ordinance" if "_municipal" in slug else "statute",
            selected=selected and bool(suffix),
            searchable=selected and bool(suffix),
            text_corpus=True,
        )
    extra = _classify_extra(name, repo)
    if extra is not None:
        return extra
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


def _classify_extra(name: str, repo: str) -> CorpusRelease | None:
    """Layouts that are not country-law IR packs and not the original pins."""

    if name == "caselaw-access-project-graphrag":
        return _row(
            corpus_id="us:caselaw-graphrag",
            hf_repo=repo,
            layout_profile="caselaw-graphrag/v1",
            coverage="snapshot",
            primary_key="law_id",
            instrument_kind="case",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name in {"caselaw_access_project", "Caselaw_Access_Project_JSON"}:
        return _row(
            corpus_id="us:caselaw",
            hf_repo=repo,
            layout_profile="caselaw-text",
            coverage="snapshot",
            primary_key="id",
            instrument_kind="case",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "world_caselaw":
        return _row(
            corpus_id="world:caselaw",
            hf_repo=repo,
            layout_profile="caselaw-text",
            coverage="snapshot",
            primary_key="id",
            instrument_kind="case",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "world_national_law_norm":
        return _row(
            corpus_id="world:national",
            hf_repo=repo,
            layout_profile="legal-record/v1",
            coverage="snapshot",
            primary_key="entry_cid",
            instrument_kind="statute",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "publicus":
        return _row(
            corpus_id="us:publicus",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="statute",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name in {"world_courts", "ipfs_world_courts"}:
        return _row(
            corpus_id="world:courts",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="court",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "world_court_forms":
        return _row(
            corpus_id="world:court-forms",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="form",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_world_court_judges":
        return _row(
            corpus_id="world:court-judges",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="court",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_world_court_rules":
        return _row(
            corpus_id="world:court-rules",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="rule",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_world_courts_directory":
        return _row(
            corpus_id="world:courts-directory",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="court",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_court_data":
        return _row(
            corpus_id="world:court-data",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="court",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "world_law_scanned_text":
        return _row(
            corpus_id="world:scanned-text",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="statute",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "world_law_scanned_pdfs":
        return _row(
            corpus_id="world:scanned-pdf",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="binary",
            primary_key="cid",
            instrument_kind="statute",
            selected=False,
            searchable=False,
            text_corpus=False,
        )
    if name == "ipfs_us_cfr":
        return _row(
            corpus_id="us:cfr",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="regulation",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_us_executive_orders":
        return _row(
            corpus_id="us:executive-orders",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="order",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_italy_municipal_statutes":
        return _row(
            corpus_id="country:italy_municipal",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="ordinance",
            selected=False,
            searchable=False,
            text_corpus=True,
        )
    if name == "ipfs_spain_laws_subnational":
        return _row(
            corpus_id="country:spain_subnational",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="statute",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name == "ipfs_juricaf_caselaw":
        return _row(
            corpus_id="world:juricaf",
            hf_repo=repo,
            layout_profile="caselaw-text",
            coverage="snapshot",
            primary_key="id",
            instrument_kind="case",
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    if name in _ARTIFACT_NAMES or any(marker in name for marker in _ARTIFACT_MARKERS):
        return _row(
            corpus_id=f"artifact:{name}",
            hf_repo=repo,
            layout_profile="excluded",
            coverage="excluded",
            primary_key="",
            instrument_kind="excluded",
            selected=False,
            searchable=False,
            text_corpus=False,
        )
    local = _LOCAL_ACTS.fullmatch(name)
    if local is not None:
        slug = _canonical_slug(local.group("slug"))
        suffix = local.group("suffix") or ""
        return _row(
            corpus_id=f"country:{slug}_local_acts",
            hf_repo=repo,
            layout_profile="country-laws-ir-graphrag/v1" if suffix == "_ir" else "legacy-split",
            coverage="snapshot",
            primary_key="entry_cid" if suffix == "_ir" else "cid",
            instrument_kind="statute",
            selected=suffix == "_ir",
            searchable=suffix == "_ir",
            text_corpus=True,
        )
    extra = _LAWS_EXTRA.fullmatch(name)
    if extra is not None:
        slug = _canonical_slug(extra.group("slug"))
        kind = extra.group("extra")
        supplement = kind == "supplement"
        return _row(
            corpus_id=f"country:{slug}:supplement" if supplement else f"country:{slug}",
            hf_repo=repo,
            layout_profile="legacy-split",
            coverage="snapshot",
            primary_key="cid",
            instrument_kind="statute",
            selected=supplement,
            searchable=supplement,
            text_corpus=True,
        )
    kind = _KIND.fullmatch(name)
    if kind is not None:
        slug = _canonical_slug(kind.group("slug"))
        label = kind.group("kind")
        if slug == "us" and label == "courts":
            corpus_id = "us:courts"
        elif label == "caselaw":
            corpus_id = f"country:{slug}:caselaw"
        elif label == "regulations":
            corpus_id = f"country:{slug}:regulations"
        else:
            corpus_id = f"country:{slug}:courts"
        if label == "caselaw":
            layout = "caselaw-text"
            primary = "id"
            instrument = "case"
        elif label == "regulations":
            layout = "legacy-split"
            primary = "cid"
            instrument = "regulation"
        else:
            layout = "legacy-split"
            primary = "cid"
            instrument = "court"
        return _row(
            corpus_id=corpus_id,
            hf_repo=repo,
            layout_profile=layout,
            coverage="snapshot",
            primary_key=primary,
            instrument_kind=instrument,
            selected=True,
            searchable=True,
            text_corpus=True,
        )
    return None


def _prefer(candidate: CorpusRelease, challenger: CorpusRelease) -> CorpusRelease:
    """Pick the repo that should be searched for one source."""

    rank = {
        "country-laws-ir-graphrag/v1": 0,
        "publicus-ir-graphrag/v2": 0,
        "patent-legal-ir-graphrag": 0,
        "caselaw-graphrag/v1": 0,
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
    challenger_org = challenger.hf_repo.split("/", 1)[0]
    candidate_org = candidate.hf_repo.split("/", 1)[0]
    if challenger_org == "justicedao" and candidate_org != "justicedao":
        return challenger
    if candidate_org == "justicedao" and challenger_org != "justicedao":
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
        org, name = _split_id(raw)
        repo = _full_id(org, name)
        if repo in seen:
            continue
        seen.add(repo)
        classified.append(_classify_one(name, org))

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
        if item.layout_profile == "unclassified":
            selected = False
        if item.coverage == "binary":
            selected = False
        if item.layout_profile in _PIN_GATED:
            selected = pin_readable(item.hf_repo)
        if item.hf_repo.rsplit("/", 1)[-1] == "american_municipal_law":
            selected = False
        group_has_norm = any(
            sibling.layout_profile == "legal-record/v1" for sibling in grouped[item.corpus_id]
        )
        if group_has_norm and item.layout_profile == "country-laws-ir-graphrag/v1":
            selected = item.selected
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
