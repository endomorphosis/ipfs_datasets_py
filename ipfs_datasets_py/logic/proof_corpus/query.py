"""Proof corpus query API (ProofCorpusQuery@1 / LIG-012).

Provides deterministic, integrity-bound lookups over a
:class:`~.store.ProofCorpusStore` using a rebuildable secondary
:class:`~.index.ProofCorpusIndex`.

Query surface:

* ``get_by_cid`` — load and re-verify one envelope
* ``list_by_source`` — all envelopes for a source digest (optional profile / family)
* ``list_by_family`` — all envelopes in one IR family
* ``list_by_profile`` — envelopes currently indexed under a profile
* ``list_constraints_for_obligation`` — Legal/Security (or other) envelopes that
  declare a given obligation digest
* ``rebuild_index`` — discard and rebuild secondary indexes from envelopes

Results are always ordered by ``content_cid`` so repeated queries over a fixed
corpus snapshot return identical sequences.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from .index import (
    ProofCorpusIndex,
    ProofCorpusIndexError,
    normalize_obligation_digest,
    rebuild_and_persist,
    rebuild_index,
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
from .store import (
    ProofCorpusStore,
    ProofCorpusStoreError,
    ProofCorpusStoreIntegrityError,
)

PROOF_CORPUS_QUERY_INTERFACE: Final = "ProofCorpusQuery@1"
PROOF_CORPUS_QUERY_SCHEMA_VERSION: Final = "proof-corpus-query/v1"

# Default families for constraint-oriented obligation lookup (plan §2.3).
_DEFAULT_CONSTRAINT_FAMILIES: Final[tuple[str, ...]] = (
    ProofCorpusFamily.LEGAL.value,
    ProofCorpusFamily.SECURITY.value,
)


class ProofCorpusQueryError(ProofCorpusSchemaError):
    """Raised when a proof-corpus query cannot proceed safely."""


class ProofCorpusQueryIntegrityError(
    ProofCorpusQueryError, ProofCorpusStoreIntegrityError
):
    """Raised when a query path fails integrity re-verification."""


def _sorted_envelopes(
    envelopes: Iterable[ArtifactEnvelope],
) -> tuple[ArtifactEnvelope, ...]:
    items = list(envelopes)
    items.sort(key=lambda env: env.content_cid)
    return tuple(items)


def _normalize_family_filter(
    families: Sequence[ProofCorpusFamily | str] | None,
) -> frozenset[str] | None:
    if families is None:
        return None
    if isinstance(families, (str, ProofCorpusFamily)):
        # Defensive: a single family value must not be iterated as characters.
        return frozenset({parse_family(families).value})
    normalized = [parse_family(item).value for item in families]
    if not normalized:
        return frozenset()
    return frozenset(normalized)


@dataclass
class ProofCorpusQuery:
    """Deterministic query facade over a multi-family proof corpus store.

    The store is the authority for envelope bytes.  The secondary index is a
    rebuildable projection; :meth:`rebuild_index` regenerates it from the store
    and is the recovery path when indexes are missing or discarded.
    """

    store: ProofCorpusStore
    index: ProofCorpusIndex | None = None
    auto_rebuild: bool = True
    _hits: int = field(default=0, init=False, repr=False)
    _misses: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.store, ProofCorpusStore):
            raise ProofCorpusQueryError(
                "ProofCorpusQuery requires a ProofCorpusStore instance"
            )
        if self.index is None and self.auto_rebuild:
            object.__setattr__(self, "index", rebuild_index(self.store))
        elif self.index is None:
            object.__setattr__(self, "index", ProofCorpusIndex.empty())

    # ------------------------------------------------------------------
    # Identity / stats
    # ------------------------------------------------------------------

    @property
    def interface(self) -> str:
        return PROOF_CORPUS_QUERY_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_CORPUS_QUERY_SCHEMA_VERSION

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "index_size": len(self._require_index()),
            "store_size": len(self.store),
        }

    def _require_index(self) -> ProofCorpusIndex:
        if self.index is None:
            raise ProofCorpusQueryError("query index is not available")
        return self.index

    def _load_cids(
        self,
        cids: Sequence[str],
        *,
        family_filter: frozenset[str] | None = None,
        profile: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Load envelopes for *cids*, re-verify integrity, apply filters."""

        if profile is not None:
            profile = require_profile(profile)
        results: list[ArtifactEnvelope] = []
        for cid in cids:
            try:
                envelope = self.store.get(cid).verify_integrity()
            except ProofCorpusStoreError as exc:
                raise ProofCorpusQueryIntegrityError(
                    f"index references missing or unreadable envelope "
                    f"content_cid={cid!r}: {exc}"
                ) from exc
            except ProofCorpusSchemaError as exc:
                raise ProofCorpusQueryIntegrityError(
                    f"envelope failed integrity for content_cid={cid!r}: {exc}"
                ) from exc
            if family_filter is not None and envelope.family.value not in family_filter:
                continue
            if profile is not None and envelope.profile != profile:
                continue
            results.append(envelope)
        ordered = _sorted_envelopes(results)
        if ordered:
            self._hits += 1
        else:
            self._misses += 1
        return ordered

    # ------------------------------------------------------------------
    # Index rebuild
    # ------------------------------------------------------------------

    def rebuild_index(self, *, persist: bool = False) -> ProofCorpusIndex:
        """Rebuild the secondary index from store envelopes.

        When *persist* is true and the store has a root directory, write both
        the store-compatible ``index.json`` projection and the full secondary
        index file.  Returns the rebuilt index (also stored on ``self.index``).
        """

        if persist and self.store.root is not None:
            index = rebuild_and_persist(self.store)
        else:
            index = rebuild_index(self.store)
        object.__setattr__(self, "index", index)
        return index

    def ensure_index(self) -> ProofCorpusIndex:
        """Return the current index, rebuilding when empty and auto_rebuild."""

        index = self._require_index()
        if len(index) == 0 and len(self.store) > 0 and self.auto_rebuild:
            return self.rebuild_index()
        return index

    # ------------------------------------------------------------------
    # Query surface (ProofCorpusQuery@1)
    # ------------------------------------------------------------------

    def get_by_cid(self, content_cid: str) -> ArtifactEnvelope:
        """Load one envelope by content CID with integrity re-verification."""

        cid = require_text(content_cid, "content_cid")
        try:
            envelope = self.store.get(cid).verify_integrity()
        except ProofCorpusStoreError as exc:
            self._misses += 1
            raise ProofCorpusQueryError(
                f"envelope not found for content_cid={cid!r}"
            ) from exc
        except ProofCorpusSchemaError as exc:
            self._misses += 1
            raise ProofCorpusQueryIntegrityError(
                f"envelope failed integrity for content_cid={cid!r}: {exc}"
            ) from exc
        self._hits += 1
        return envelope

    def list_by_source(
        self,
        source_digest: str,
        *,
        profile: str | None = None,
        family: ProofCorpusFamily | str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return envelopes for a source digest (deterministic CID order).

        Optional *profile* and *family* narrow the result.  An empty tuple is
        returned when nothing matches (not an error).
        """

        source_digest = require_digest(source_digest, "source_digest")
        index = self.ensure_index()
        cids = index.cids_for_source(source_digest, profile=profile)
        family_filter = (
            frozenset({parse_family(family).value}) if family is not None else None
        )
        # If the index is stale relative to the store, fall back to a store
        # scan for this source so queries remain correct after puts without an
        # explicit rebuild.
        if not cids:
            cids = self._source_cids_from_store(source_digest, profile=profile)
        return self._load_cids(cids, family_filter=family_filter, profile=profile)

    def _source_cids_from_store(
        self,
        source_digest: str,
        *,
        profile: str | None = None,
    ) -> tuple[str, ...]:
        matched: list[str] = []
        for cid in self.store.cids():
            envelope = self.store.get(cid)
            if envelope.source_digest != source_digest:
                continue
            if profile is not None and envelope.profile != profile:
                continue
            matched.append(cid)
        return tuple(sorted(matched))

    def list_by_family(
        self, family: ProofCorpusFamily | str
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return all stored envelopes for one family (sorted by content_cid)."""

        family_key = parse_family(family).value
        index = self.ensure_index()
        cids = index.cids_for_family(family_key)
        if not cids:
            # Fall back to store family listing (already sorted).
            envelopes = self.store.list_by_family(family_key)
            if envelopes:
                self._hits += 1
            else:
                self._misses += 1
            return envelopes
        return self._load_cids(cids, family_filter=frozenset({family_key}))

    def list_by_profile(
        self, profile: str
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return envelopes currently indexed for *profile*.

        Profile index is last-writer-wins per store semantics; the result is a
        0- or 1-element tuple for the unified store index, still returned as a
        sequence for API uniformity.
        """

        profile = require_profile(profile)
        index = self.ensure_index()
        cids = index.cids_for_profile(profile)
        if not cids:
            try:
                envelope = self.store.get_by_profile(profile)
            except ProofCorpusStoreError:
                self._misses += 1
                return ()
            self._hits += 1
            return (envelope.verify_integrity(),)
        return self._load_cids(cids, profile=profile)

    def list_constraints_for_obligation(
        self,
        obligation_digest: str | None = None,
        *,
        obligation_id: str | None = None,
        families: Sequence[ProofCorpusFamily | str] | None = _DEFAULT_CONSTRAINT_FAMILIES,
        profile: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return constraint envelopes that declare the given obligation.

        At least one of *obligation_digest* or *obligation_id* is required.
        When both are provided the result is the intersection.

        Default *families* are ``legal`` and ``security`` (constraint families
        for the admissibility join).  Pass ``families=None`` to include every
        family (including Intent).  Results are sorted by ``content_cid``.
        """

        if obligation_digest is None and obligation_id is None:
            raise ProofCorpusQueryError(
                "list_constraints_for_obligation requires obligation_digest "
                "or obligation_id"
            )

        index = self.ensure_index()
        family_filter = _normalize_family_filter(families)

        cid_sets: list[set[str]] = []
        if obligation_digest is not None:
            digest = normalize_obligation_digest(obligation_digest)
            cid_sets.append(set(index.cids_for_obligation_digest(digest)))
            # Index may be empty for obligations if only a store projection was
            # loaded; fall back to a full envelope scan.
            if not cid_sets[-1]:
                cid_sets[-1] = set(
                    self._scan_cids_for_obligation_digest(digest)
                )
        if obligation_id is not None:
            oid = require_text(obligation_id, "obligation_id")
            cid_sets.append(set(index.cids_for_obligation_id(oid)))
            if not cid_sets[-1]:
                cid_sets[-1] = set(self._scan_cids_for_obligation_id(oid))

        if not cid_sets:
            self._misses += 1
            return ()
        matched = set.intersection(*cid_sets) if len(cid_sets) > 1 else cid_sets[0]
        return self._load_cids(
            sorted(matched),
            family_filter=family_filter,
            profile=profile,
        )

    def _scan_cids_for_obligation_digest(self, digest: str) -> tuple[str, ...]:
        matched: list[str] = []
        for cid in self.store.cids():
            envelope = self.store.get(cid)
            for obligation in envelope.formalization_artifact().proof_obligations:
                if normalize_obligation_digest(obligation.digest) == digest:
                    matched.append(cid)
                    break
        return tuple(sorted(matched))

    def _scan_cids_for_obligation_id(self, obligation_id: str) -> tuple[str, ...]:
        matched: list[str] = []
        for cid in self.store.cids():
            envelope = self.store.get(cid)
            for obligation in envelope.formalization_artifact().proof_obligations:
                if obligation.obligation_id == obligation_id:
                    matched.append(cid)
                    break
        return tuple(sorted(matched))

    def list_all(
        self,
        *,
        family: ProofCorpusFamily | str | None = None,
        profile: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Return all envelopes, optionally filtered, in CID order."""

        if family is not None:
            envelopes = self.list_by_family(family)
            if profile is not None:
                profile = require_profile(profile)
                envelopes = tuple(
                    env for env in envelopes if env.profile == profile
                )
            return envelopes
        index = self.ensure_index()
        cids = index.all_cids()
        if not cids:
            cids = self.store.cids()
        return self._load_cids(cids, profile=profile)

    def query(
        self,
        *,
        content_cid: str | None = None,
        source_digest: str | None = None,
        family: ProofCorpusFamily | str | None = None,
        profile: str | None = None,
        obligation_digest: str | None = None,
        obligation_id: str | None = None,
        constraint_families: Sequence[ProofCorpusFamily | str] | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        """Multi-filter query with deterministic CID ordering.

        When *content_cid* is set, returns a single-envelope tuple or empty.
        Obligation filters use constraint-family defaults unless
        *constraint_families* is provided (``None`` keeps default legal+security
        when an obligation filter is active; pass ``()`` empty only via an
        explicit empty sequence is not allowed — use ``families`` on
        :meth:`list_constraints_for_obligation` for full control).
        """

        if content_cid is not None:
            try:
                return (self.get_by_cid(content_cid),)
            except ProofCorpusQueryError:
                return ()

        if obligation_digest is not None or obligation_id is not None:
            families: Sequence[ProofCorpusFamily | str] | None
            if constraint_families is not None:
                families = constraint_families
            elif family is not None:
                families = (family,)
            else:
                families = _DEFAULT_CONSTRAINT_FAMILIES
            results = self.list_constraints_for_obligation(
                obligation_digest,
                obligation_id=obligation_id,
                families=families,
                profile=profile,
            )
            if source_digest is not None:
                source_digest = require_digest(source_digest, "source_digest")
                results = tuple(
                    env for env in results if env.source_digest == source_digest
                )
            return results

        if source_digest is not None:
            return self.list_by_source(
                source_digest, profile=profile, family=family
            )
        if family is not None:
            return self.list_by_family(family) if profile is None else self.list_all(
                family=family, profile=profile
            )
        if profile is not None:
            return self.list_by_profile(profile)
        return self.list_all()


def open_query(
    store: ProofCorpusStore,
    *,
    index: ProofCorpusIndex | None = None,
    auto_rebuild: bool = True,
) -> ProofCorpusQuery:
    """Construct a :class:`ProofCorpusQuery` over *store*."""

    return ProofCorpusQuery(store=store, index=index, auto_rebuild=auto_rebuild)


__all__ = [
    "PROOF_CORPUS_QUERY_INTERFACE",
    "PROOF_CORPUS_QUERY_SCHEMA_VERSION",
    "ProofCorpusQuery",
    "ProofCorpusQueryError",
    "ProofCorpusQueryIntegrityError",
    "open_query",
]
