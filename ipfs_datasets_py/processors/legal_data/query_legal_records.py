"""Worldwide legal query. One schema, one jurisdiction, no US fallback.

``LEGAL_QUERY_NORMALIZED`` defaults off. The flag is checked before
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


class LegalQueryDisabled(RuntimeError):
    """Raised when LEGAL_QUERY_NORMALIZED is unset or not ``1``."""


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
    corpus_opener: Callable[[str], tuple[dict[str, object], ...]] | None = None,
) -> LegalQueryResult:
    """Return legal-record/v1 rows for one jurisdiction.

    ``language`` is accepted and reserved for the corpus reader. ``limit``
    is clamped to 1..100. Neither value is applied until a reader is passed.
    """

    if os.environ.get(_FLAG) != "1":
        raise LegalQueryDisabled(
            "LEGAL_QUERY_NORMALIZED must be 1 before a jurisdiction is resolved"
        )
    if limit < 1 or limit > 100:
        raise LegalQueryInputError("limit_out_of_range")
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

    _require_query_shape(
        resolved,
        text_query=text_query,
        citation=citation,
        instrument_type=instrument_type,
        admin_level=admin_level,
    )
    route = _route(
        resolved,
        instrument_type=instrument_type,
        admin_level=admin_level,
        allow_stale=allow_stale,
        gap_status=gap_status,
        alias_revisions=alias_revisions,
    )
    records: tuple[dict[str, object], ...] = ()
    if route.open_repo is not None and corpus_opener is not None:
        records = tuple(corpus_opener(route.open_repo))[:limit]
    if route.coverage == "partial" and gap_status:
        records = tuple(_stamp_fallback(row, gap_status) for row in records)
    return _result(
        jurisdiction=route.jurisdiction,
        coverage=route.coverage,
        source_repo=route.source_repo,
        source_revision=route.source_revision,
        records=records,
        query_id=query_id,
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
) -> None:
    statute_like = instrument_type in {None, "", "statute"}
    if resolved.code == "US" and statute_like and not admin_level:
        raise LegalQueryInputError("admin_level_required")
    if not (text_query or "").strip() and not (citation or "").strip():
        raise LegalQueryInputError("query_required")


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


def _stamp_fallback(row: dict[str, object], gap_status: str) -> dict[str, object]:
    copied = dict(row)
    raw = copied.get("provenance")
    provenance = dict(raw) if isinstance(raw, dict) else {}
    provenance["fallback_from"] = gap_status
    copied["provenance"] = provenance
    return copied


def _closed(echo: str) -> _Route:
    return _Route(echo, "not_published", None, None, None)


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
    )
