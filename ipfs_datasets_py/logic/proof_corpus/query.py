"""Proof corpus query API (ProofCorpusQuery@1 / LIG-012).

Deterministic query surface over a :class:`ProofCorpusStore` and a rebuildable
:class:`ProofCorpusIndex`.  Envelopes remain authoritative; the index is a pure
secondary view rebuilt from them.

Supported lookups:

* **by CID** — integrity-bound envelope load
* **by source** — source digest and/or source id, optional profile/family
* **by family** — Intent / Legal / Security postings
* **by profile** — profile-keyed envelope
* **by obligation digest** — envelopes whose formalization carries the digest
  (``list_constraints_for_obligation`` prefers Legal/Security constraint
  families unless *family* is specified)

All multi-result methods return envelopes sorted by ``content_cid``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from .index import (
    PROOF_CORPUS_INDEX_INTERFACE,
    ProofCorpusIndex,
    ProofCorpusIndexError,
    normalize_obligation_digest,
    rebuild_index_from_store,
)
from .schemas import (
    ArtifactEnvelope,
    ProofCorpusFamily,
    ProofCorpusSchemaError,
    parse_family,
    require_digest,
    require_profile,
    require_text,
)
from .store import ProofCorpusStore, ProofCorpusStoreError


PROOF_CORPUS_QUERY_INTERFACE: Final = "ProofCorpusQuery@1"
PROOF_CORPUS_QUERY_SCHEMA_VERSION: Final = "proof-corpus-query/v1"

# Default constraint families for obligation joins (admissibility consumers).
_CONSTRAINT_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        ProofCorpusFamily.LEGAL.value,
        ProofCorpusFamily.SECURITY.value,
    }
)


class ProofCorpusQueryError(ProofCorpusSchemaError):
    """Raised when a proof-corpus query cannot proceed safely."""


@dataclass
class ProofCorpusQuery:
    """ProofCorpusQuery@1 — deterministic multi-key query over a store.

    The index is rebuilt lazily from the store on first query unless an
    explicit :class:`ProofCorpusIndex` is supplied.  Call
    :meth:`rebuild_index` after mutations so postings stay in sync.
    """

    store: ProofCorpusStore
    index: ProofCorpusIndex | None = None
    _auto_index: ProofCorpusIndex | None = field(
        default=None, init=False, repr=False
    )

    @property
    def interface(self) -> str:
        return PROOF_CORPUS_QUERY_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_CORPUS_QUERY_SCHEMA_VERSION

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------

    def _active_index(self) -> ProofCorpusIndex:
        if self.index is not None:
            return self.index
        if self._auto_index is None:
            self._auto_index = rebuild_index_from_store(self.store)
        return self._auto_index

    def rebuild_index(self) -> ProofCorpusIndex:
        """Rebuild secondary indexes from every envelope currently in the store.

        Returns the rebuilt index and installs it as the active query index.
        """

        rebuilt = rebuild_index_from_store(self.store)
        self.index = rebuilt
        self._auto_index = rebuilt
        return rebuilt

    def ensure_index(self) -> ProofCorpusIndex:
        """Return the active index, rebuilding from the store if needed."""

        return self._active_index()

    # ------------------------------------------------------------------
    # Envelope resolution helpers
    # ------------------------------------------------------------------

    def _resolve_cids(
        self,
        cids: Sequence[str],
        *,
        family: ProofCorpusFamily | str | None = None,
        profile: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        family_filter: ProofCorpusFamily | None = (
            parse_family(family) if family is not None else None
        )
        profile_filter = (
            require_profile(profile) if profile is not None else None
        )
        results: list[ArtifactEnvelope] = []
        for cid in sorted(set(cids)):
            try:
                envelope = self.store.get(cid)
            except ProofCorpusStoreError:
                # Index drift: fail closed rather than silently dropping.
                raise ProofCorpusQueryError(
                    f"query index references missing envelope content_cid={cid!r}"
                ) from None
            if family_filter is not None and envelope.family is not family_filter:
                continue
            if profile_filter is not None and envelope.profile != profile_filter:
                continue
            results.append(envelope.verify_integrity())
        results.sort(key=lambda env: env.content_cid)
        return tuple(results)

    # ------------------------------------------------------------------
    # Query surface
    # ------------------------------------------------------------------

    def get_by_cid(self, content_cid: str) -> ArtifactEnvelope:
        """Load and re-verify one envelope by content CID."""

        return self.store.get(require_text(content_cid, "content_cid"))

    def list_by_family(
        self,
        family: ProofCorpusFamily | str,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return all envelopes for *family*, sorted by content CID."""

        index = self._active_index()
        cids = index.cids_for_family(family)
        return self._resolve_cids(cids, family=family)

    def list_by_profile(self, profile: str) -> tuple[ArtifactEnvelope, ...]:
        """Return envelopes currently indexed under *profile* (0 or 1)."""

        index = self._active_index()
        cids = index.cids_for_profile(profile)
        return self._resolve_cids(cids, profile=profile)

    def list_by_source(
        self,
        *,
        source_digest: str | None = None,
        source_id: str | None = None,
        profile: str | None = None,
        family: ProofCorpusFamily | str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return envelopes matching source identity.

        At least one of *source_digest* or *source_id* is required.  When both
        are provided, results are the intersection.  Optional *profile* and
        *family* further narrow the set.  Ordering is by ``content_cid``.
        """

        if source_digest is None and source_id is None:
            raise ProofCorpusQueryError(
                "list_by_source requires source_digest and/or source_id"
            )

        index = self._active_index()
        cid_sets: list[set[str]] = []

        if source_digest is not None:
            digest = require_digest(source_digest, "source_digest")
            cid_sets.append(
                set(
                    index.cids_for_source_digest(
                        digest, profile=profile if source_id is None else None
                    )
                )
            )
        if source_id is not None:
            sid = require_text(source_id, "source_id")
            cid_sets.append(set(index.cids_for_source_id(sid)))

        if not cid_sets:
            return ()
        cids = set.intersection(*cid_sets) if len(cid_sets) > 1 else cid_sets[0]
        return self._resolve_cids(sorted(cids), family=family, profile=profile)

    def list_constraints_for_obligation(
        self,
        obligation_digest: str,
        *,
        family: ProofCorpusFamily | str | None = None,
        profile: str | None = None,
        include_intent: bool = False,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return constraint envelopes that carry *obligation_digest*.

        By default only Legal and Security envelopes are returned (constraint
        families).  Pass *family* to restrict to one family, or set
        *include_intent* True to also include Intent formalizations that share
        the obligation digest.  Results are sorted by ``content_cid``.
        """

        digest = normalize_obligation_digest(obligation_digest)
        index = self._active_index()
        cids = index.cids_for_obligation(digest)
        envelopes = self._resolve_cids(cids, family=family, profile=profile)

        if family is not None:
            return envelopes

        if include_intent:
            return envelopes

        return tuple(
            env
            for env in envelopes
            if env.family.value in _CONSTRAINT_FAMILIES
        )

    def list_by_obligation(
        self,
        obligation_digest: str,
        *,
        family: ProofCorpusFamily | str | None = None,
        profile: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return every envelope (any family) that carries *obligation_digest*."""

        digest = normalize_obligation_digest(obligation_digest)
        index = self._active_index()
        return self._resolve_cids(
            index.cids_for_obligation(digest),
            family=family,
            profile=profile,
        )

    def query(
        self,
        *,
        content_cid: str | None = None,
        family: ProofCorpusFamily | str | None = None,
        profile: str | None = None,
        source_digest: str | None = None,
        source_id: str | None = None,
        obligation_digest: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Composite filter query with deterministic intersection semantics.

        Providing *content_cid* alone is equivalent to :meth:`get_by_cid`
        wrapped in a one-element tuple (or empty on miss).  Combining filters
        intersects CID postings before resolution.  At least one filter is
        required.
        """

        filters_present = any(
            value is not None
            for value in (
                content_cid,
                family,
                profile,
                source_digest,
                source_id,
                obligation_digest,
            )
        )
        if not filters_present:
            raise ProofCorpusQueryError(
                "query requires at least one filter "
                "(content_cid, family, profile, source_digest, "
                "source_id, or obligation_digest)"
            )

        if content_cid is not None and all(
            value is None
            for value in (
                family,
                profile,
                source_digest,
                source_id,
                obligation_digest,
            )
        ):
            try:
                return (self.get_by_cid(content_cid),)
            except ProofCorpusStoreError:
                return ()

        index = self._active_index()
        cid_sets: list[set[str]] = []

        if content_cid is not None:
            cid = require_text(content_cid, "content_cid")
            cid_sets.append({cid} if index.contains(cid) or self.store.contains(cid) else set())

        if family is not None:
            cid_sets.append(set(index.cids_for_family(family)))

        if profile is not None:
            cid_sets.append(set(index.cids_for_profile(profile)))

        if source_digest is not None:
            digest = require_digest(source_digest, "source_digest")
            cid_sets.append(set(index.cids_for_source_digest(digest)))

        if source_id is not None:
            sid = require_text(source_id, "source_id")
            cid_sets.append(set(index.cids_for_source_id(sid)))

        if obligation_digest is not None:
            odigest = normalize_obligation_digest(obligation_digest)
            cid_sets.append(set(index.cids_for_obligation(odigest)))

        if not cid_sets:
            return ()
        cids = set.intersection(*cid_sets)
        return self._resolve_cids(
            sorted(cids),
            family=family,
            profile=profile,
        )

    def list_all(self) -> tuple[ArtifactEnvelope, ...]:
        """Return every indexed envelope sorted by content CID."""

        index = self._active_index()
        return self._resolve_cids(index.content_cids)

    def stats(self) -> dict[str, Any]:
        """Return deterministic query/index statistics."""

        index = self._active_index()
        store_stats = self.store.stats()
        return {
            "interface": self.interface,
            "schema_version": self.schema_version,
            "index_interface": index.interface or PROOF_CORPUS_INDEX_INTERFACE,
            "index_schema_version": index.schema_version,
            "envelope_count": len(index),
            "family_count": len(index.families),
            "profile_count": len(index.profiles),
            "source_digest_count": len(index.sources),
            "source_id_count": len(index.source_ids),
            "obligation_count": len(index.obligations),
            "store_hits": store_stats["hits"],
            "store_misses": store_stats["misses"],
            "store_size": store_stats["size"],
        }


def query_corpus(
    store: ProofCorpusStore,
    **filters: Any,
) -> tuple[ArtifactEnvelope, ...]:
    """Module-level helper: run a composite :meth:`ProofCorpusQuery.query`."""

    return ProofCorpusQuery(store=store).query(**filters)


def get_by_cid(store: ProofCorpusStore, content_cid: str) -> ArtifactEnvelope:
    """Module-level get-by-CID helper (ProofCorpusQuery@1 surface)."""

    return ProofCorpusQuery(store=store).get_by_cid(content_cid)


def list_by_source(
    store: ProofCorpusStore,
    **kwargs: Any,
) -> tuple[ArtifactEnvelope, ...]:
    """Module-level list-by-source helper."""

    return ProofCorpusQuery(store=store).list_by_source(**kwargs)


def list_constraints_for_obligation(
    store: ProofCorpusStore,
    obligation_digest: str,
    **kwargs: Any,
) -> tuple[ArtifactEnvelope, ...]:
    """Module-level obligation→constraint join helper."""

    return ProofCorpusQuery(store=store).list_constraints_for_obligation(
        obligation_digest, **kwargs
    )


__all__ = [
    "PROOF_CORPUS_QUERY_INTERFACE",
    "PROOF_CORPUS_QUERY_SCHEMA_VERSION",
    "ProofCorpusQuery",
    "ProofCorpusQueryError",
    "get_by_cid",
    "list_by_source",
    "list_constraints_for_obligation",
    "query_corpus",
]
