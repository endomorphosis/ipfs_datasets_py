"""Content-addressed premise corpus and theorem manifest for the ITP hammer
pipeline (HAMMER-003).

This module implements the versioned corpus manifest described in
``docs/logic/itp_hammer_corpus.md`` and the ``## HAMMER-003`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``. It is the *only* place theorems
and premises may be ingested into the hammer pipeline: every entry must
belong to a declared :class:`CorpusSource` (no anonymous or ad-hoc premises),
carries a stable ``theorem_id`` identity, its source ITP, its ``imports``,
a deterministic ``normalized_statement`` digest, license metadata, and a
content digest/CID computed from the entry's canonical form (never supplied
by the caller).

Building blocks
----------------
- :class:`CorpusSource` — a declared upstream theorem corpus (e.g. a pinned
  Mathlib4/Rocq-stdlib/AFP snapshot) with its own license metadata. Theorems
  may only be ingested against a corpus that has been registered here first.
- :class:`TheoremEntry` — one theorem/premise identity ingested from a
  declared :class:`CorpusSource`, with a normalized-statement digest, license
  metadata, and a content digest/CID.
- :class:`CorpusManifest` — the versioned collection of declared sources and
  ingested theorem entries. ``CorpusManifest.revision`` is a deterministic
  digest over the manifest's full content and is the value that must be
  threaded through :class:`ipfs_datasets_py.logic.hammers.models.HammerRequest`
  and :class:`ipfs_datasets_py.logic.hammers.models.HammerResult` as
  ``corpus_revision``.
- :func:`verify_hammer_result_corpus` — ties a
  :class:`~ipfs_datasets_py.logic.hammers.models.HammerResult` back to a
  specific manifest snapshot, so every hammer result can be shown to have
  used premises from one specific, auditable corpus revision.

Identity and duplicate rejection
---------------------------------
``theorem_id`` is the corpus-wide identity of a theorem/premise. Ingesting a
second entry under an already-known ``theorem_id`` is only permitted when its
normalized statement digests to the *same* value as the existing entry
(idempotent re-ingestion, e.g. re-running an ingestion job against an
unchanged upstream snapshot). Ingesting the same ``theorem_id`` with a
*different* statement — or a different source ITP/corpus — raises
:class:`DuplicateTheoremIdentityError`. This is what "reject duplicate
identities with different statements" means operationally: identity is a
promise about a single, fixed statement, never a mutable label.

Content addressing
-------------------
:func:`compute_content_digest` produces a real CIDv1 (``base32``, ``raw``
codec, ``sha2-256`` multihash) via the ``multiformats`` package when it is
importable, and falls back to a plain ``"sha256:<hex>"`` deterministic digest
string otherwise. Either form satisfies the "CID or deterministic content
digest" requirement; callers should treat the returned string as opaque and
compare it for equality only.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    SCHEMA_VERSION,
    ITPKind,
    _isoformat,
    _parse_datetime,
    _require_nonempty_str,
    _require_schema_version,
    _utcnow,
)

__all__ = [
    "SCHEMA_VERSION",
    "CorpusError",
    "UndeclaredCorpusSourceError",
    "CorpusSourceConflictError",
    "DuplicateTheoremIdentityError",
    "CorpusRevisionMismatchError",
    "CorpusSource",
    "TheoremEntry",
    "CorpusManifest",
    "normalize_statement",
    "compute_statement_digest",
    "compute_content_digest",
    "verify_hammer_result_corpus",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CorpusError(ValueError):
    """Base class for all corpus/manifest errors raised by this module."""


class UndeclaredCorpusSourceError(CorpusError):
    """Raised when ingesting a theorem against a ``corpus_id`` that has not
    been registered via :meth:`CorpusManifest.register_source`.

    Only *declared* theorem corpora may be ingested — this exception is what
    enforces that rule.
    """


class CorpusSourceConflictError(CorpusError):
    """Raised when re-registering a ``corpus_id`` with different metadata
    than the already-registered :class:`CorpusSource` (e.g. a different
    ``version_ref`` or ``license_id``), which would silently change the
    provenance of every theorem already ingested under that corpus."""


class DuplicateTheoremIdentityError(CorpusError):
    """Raised when a ``theorem_id`` already present in the manifest is
    ingested again with a different normalized-statement digest, source ITP,
    or corpus — i.e. the same identity would now refer to a different
    theorem. Re-ingesting an identical statement under the same identity and
    corpus is allowed and is a no-op."""


class CorpusRevisionMismatchError(CorpusError):
    """Raised by :func:`verify_hammer_result_corpus` when a
    :class:`~ipfs_datasets_py.logic.hammers.models.HammerResult` (or one of
    its premises) does not match the corpus manifest it is checked against."""


# ---------------------------------------------------------------------------
# Deterministic normalization and content addressing
# ---------------------------------------------------------------------------

_WHITESPACE_RUN_RE = re.compile(r"[ \t]+")


def normalize_statement(statement: str) -> str:
    """Canonicalize a theorem/premise statement for digesting.

    This normalization is intentionally simple and ITP-agnostic (it does not
    parse or understand Lean/Coq/Isabelle syntax): it performs Unicode NFC
    normalization, unifies line endings, strips leading/trailing whitespace
    on every line, drops blank lines, and collapses runs of horizontal
    whitespace to a single space. The goal is *not* semantic equivalence
    across whitespace-insensitive rewrites of a proof term — it is a stable,
    reproducible digest input so that byte-identical re-ingestion of the same
    upstream source always produces the same
    :func:`compute_statement_digest` value, while trivial formatting noise
    (CRLF vs LF, trailing spaces, extra blank lines) does not spuriously
    change a theorem's identity digest.

    Args:
        statement: The raw statement text as authored in its source ITP.

    Returns:
        The normalized statement text.

    Raises:
        ValueError: If ``statement`` is not a non-empty string.
    """

    if not isinstance(statement, str) or not statement.strip():
        raise ValueError("statement must be a non-empty string")

    text = unicodedata.normalize("NFC", statement)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    normalized = "\n".join(lines)
    normalized = _WHITESPACE_RUN_RE.sub(" ", normalized)
    return normalized.strip()


def compute_statement_digest(normalized_statement: str) -> str:
    """Compute the deterministic digest of an already-normalized statement.

    Args:
        normalized_statement: The output of :func:`normalize_statement`.

    Returns:
        A ``"sha256:<hex>"`` digest string.
    """

    if not isinstance(normalized_statement, str) or not normalized_statement:
        raise ValueError("normalized_statement must be a non-empty string")
    digest = hashlib.sha256(normalized_statement.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")


def compute_content_digest(payload: Any) -> str:
    """Compute a deterministic content digest/CID for ``payload``.

    ``payload`` is serialized to canonical JSON (sorted keys, no
    non-determinism from dict ordering, ``ensure_ascii=True``) and hashed with
    SHA-256. When the optional ``multiformats`` package is importable, the
    digest is additionally wrapped as a real CIDv1 (``base32`` multibase,
    ``raw`` multicodec, ``sha2-256`` multihash) string such as
    ``"bafkrei..."``. When ``multiformats`` is unavailable, a plain
    ``"sha256:<hex>"`` string is returned instead. Both forms are equally
    valid, deterministic content digests for this corpus's purposes; callers
    must only compare them for equality, never parse their internal
    structure.

    Args:
        payload: Any JSON-serializable value (dicts, lists, strings,
            numbers, booleans, ``None``).

    Returns:
        A CID string (when ``multiformats`` is available) or a
        ``"sha256:<hex>"`` fallback digest string.
    """

    data = _canonical_json_bytes(payload)
    sha256_hex = hashlib.sha256(data).hexdigest()
    try:
        from multiformats import CID, multihash  # type: ignore[import-not-found]

        mh = multihash.wrap(bytes.fromhex(sha256_hex), "sha2-256")
        return str(CID("base32", 1, "raw", mh))
    except Exception:
        # multiformats is an optional dependency for this module (it is a
        # required dependency of the package as a whole, but this module
        # must keep working — with a deterministic, if non-CID, digest — even
        # if it is ever missing or raises for an unexpected reason).
        return f"sha256:{sha256_hex}"


# ---------------------------------------------------------------------------
# Corpus source
# ---------------------------------------------------------------------------


@dataclass
class CorpusSource:
    """A declared upstream theorem corpus.

    Theorems may only be ingested into a :class:`CorpusManifest` against a
    ``corpus_id`` that has first been registered as a ``CorpusSource`` — this
    is what "ingest only declared theorem corpora" means operationally.

    Attributes:
        schema_version: Schema version of this record.
        corpus_id: Stable identifier of this corpus within the manifest
            (e.g. ``"mathlib4"``, ``"rocq-stdlib"``, ``"afp"``).
        name: Human-readable name of the corpus.
        source_itp: The ITP this corpus's theorems are native to.
        version_ref: The exact upstream snapshot ingested (a git commit,
            tag, or release version) — never a floating "latest" reference,
            so ingestion is always reproducible.
        license_id: Default SPDX license identifier for theorems from this
            corpus (e.g. ``"Apache-2.0"``); may be overridden per theorem.
        license_url: Optional URL to the license text or the corpus's
            license file.
        homepage: Optional URL to the corpus's homepage/repository.
        description: Optional human-readable description.
        metadata: Free-form, non-authoritative caller metadata.
    """

    schema_version: str = SCHEMA_VERSION
    corpus_id: str = ""
    name: str = ""
    source_itp: ITPKind = ITPKind.LEAN
    version_ref: str = ""
    license_id: str = ""
    license_url: Optional[str] = None
    homepage: Optional[str] = None
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="CorpusSource")
        _require_nonempty_str(self.corpus_id, field_name="corpus_id", owner="CorpusSource")
        _require_nonempty_str(self.name, field_name="name", owner="CorpusSource")
        if not isinstance(self.source_itp, ITPKind):
            raise ValueError("CorpusSource.source_itp must be an ITPKind")
        _require_nonempty_str(
            self.version_ref, field_name="version_ref", owner="CorpusSource"
        )
        _require_nonempty_str(
            self.license_id, field_name="license_id", owner="CorpusSource"
        )
        if self.license_url is not None and not isinstance(self.license_url, str):
            raise ValueError("CorpusSource.license_url must be a string or None")
        if self.homepage is not None and not isinstance(self.homepage, str):
            raise ValueError("CorpusSource.homepage must be a string or None")
        if not isinstance(self.description, str):
            raise ValueError("CorpusSource.description must be a string")
        if not isinstance(self.metadata, dict):
            raise ValueError("CorpusSource.metadata must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_itp"] = self.source_itp.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorpusSource":
        data = dict(data)
        if isinstance(data.get("source_itp"), str):
            data["source_itp"] = ITPKind(data["source_itp"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Theorem entry
# ---------------------------------------------------------------------------


@dataclass
class TheoremEntry:
    """One theorem/premise identity ingested from a declared corpus source.

    Instances should be constructed via :meth:`create` (used internally by
    :meth:`CorpusManifest.add_theorem`) rather than directly, so that
    ``normalized_statement``, ``statement_digest``, and ``content_digest``
    are always *derived* from ``statement`` and never independently supplied
    (and therefore never able to drift from, or spoof, the actual content).

    Attributes:
        schema_version: Schema version of this record.
        theorem_id: Stable identity of this theorem within the manifest.
        corpus_id: The :class:`CorpusSource.corpus_id` this entry was
            ingested from.
        source_itp: ITP this theorem's statement is native to; must match
            the owning :class:`CorpusSource.source_itp`.
        imports: Ordered list of module/theory/file dependencies the
            statement requires (e.g. ``["Mathlib.Algebra.Group.Defs"]``).
        statement: The raw statement text, as authored.
        normalized_statement: The canonicalized form of ``statement`` (see
            :func:`normalize_statement`) used to compute ``statement_digest``.
        statement_digest: Deterministic digest of ``normalized_statement``
            (see :func:`compute_statement_digest`). This is the "normalized
            statement digest" that theorem identity is checked against.
        license_id: SPDX license identifier for this specific theorem
            (defaults to the owning corpus's ``license_id``).
        license_url: Optional URL to the license text (defaults to the
            owning corpus's ``license_url``).
        content_digest: Deterministic content digest/CID of this entire
            entry's canonical, identity-defining fields (see
            :func:`compute_content_digest`).
        metadata: Free-form, non-authoritative caller metadata (e.g. source
            file path, line number).
        ingested_at: When this entry was ingested into the manifest.
    """

    schema_version: str = SCHEMA_VERSION
    theorem_id: str = ""
    corpus_id: str = ""
    source_itp: ITPKind = ITPKind.LEAN
    imports: List[str] = field(default_factory=list)
    statement: str = ""
    normalized_statement: str = ""
    statement_digest: str = ""
    license_id: str = ""
    license_url: Optional[str] = None
    content_digest: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    ingested_at: datetime = field(default_factory=_utcnow)

    @classmethod
    def create(
        cls,
        *,
        theorem_id: str,
        corpus_id: str,
        source_itp: ITPKind,
        statement: str,
        imports: Optional[Iterable[str]] = None,
        license_id: str,
        license_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "TheoremEntry":
        """Build a :class:`TheoremEntry`, deriving all digests from
        ``statement``. This is the only supported construction path outside
        of deserialization via :meth:`from_dict`."""

        _require_nonempty_str(theorem_id, field_name="theorem_id", owner="TheoremEntry")
        _require_nonempty_str(corpus_id, field_name="corpus_id", owner="TheoremEntry")
        if not isinstance(source_itp, ITPKind):
            raise ValueError("TheoremEntry.source_itp must be an ITPKind")
        _require_nonempty_str(license_id, field_name="license_id", owner="TheoremEntry")

        normalized = normalize_statement(statement)
        statement_digest = compute_statement_digest(normalized)
        imports_list = sorted(dict.fromkeys(imports or []))
        metadata_dict = dict(metadata or {})

        entry = cls(
            theorem_id=theorem_id,
            corpus_id=corpus_id,
            source_itp=source_itp,
            imports=imports_list,
            statement=statement,
            normalized_statement=normalized,
            statement_digest=statement_digest,
            license_id=license_id,
            license_url=license_url,
            metadata=metadata_dict,
        )
        entry.content_digest = compute_content_digest(entry._identity_payload())
        entry.validate()
        return entry

    def _identity_payload(self) -> Dict[str, Any]:
        """The canonical, identity-defining subset of fields used to compute
        ``content_digest``. Deliberately excludes ``content_digest`` itself
        (which would be circular) and ``ingested_at`` (a digest must not
        change just because the same theorem was re-ingested later)."""

        return {
            "theorem_id": self.theorem_id,
            "corpus_id": self.corpus_id,
            "source_itp": self.source_itp.value,
            "imports": list(self.imports),
            "statement_digest": self.statement_digest,
            "license_id": self.license_id,
            "license_url": self.license_url,
        }

    def _revision_payload(self) -> Dict[str, Any]:
        """The subset of :meth:`to_dict` used when computing a
        :class:`CorpusManifest`'s ``revision``. Excludes ``ingested_at``
        (wall-clock ingestion time is never part of content identity — two
        manifests built from byte-identical sources at different times must
        get the same revision) but otherwise includes every field, including
        ``metadata``, so the revision reflects the manifest's full content."""

        data = self.to_dict()
        data.pop("ingested_at", None)
        return data

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="TheoremEntry")
        _require_nonempty_str(self.theorem_id, field_name="theorem_id", owner="TheoremEntry")
        _require_nonempty_str(self.corpus_id, field_name="corpus_id", owner="TheoremEntry")
        if not isinstance(self.source_itp, ITPKind):
            raise ValueError("TheoremEntry.source_itp must be an ITPKind")
        if not isinstance(self.imports, list) or not all(
            isinstance(item, str) for item in self.imports
        ):
            raise ValueError("TheoremEntry.imports must be a list of strings")
        _require_nonempty_str(self.statement, field_name="statement", owner="TheoremEntry")
        _require_nonempty_str(
            self.normalized_statement,
            field_name="normalized_statement",
            owner="TheoremEntry",
        )
        _require_nonempty_str(
            self.statement_digest, field_name="statement_digest", owner="TheoremEntry"
        )
        if not self.statement_digest.startswith("sha256:"):
            raise ValueError(
                "TheoremEntry.statement_digest must be a 'sha256:<hex>' digest, got "
                f"{self.statement_digest!r}"
            )
        _require_nonempty_str(
            self.license_id, field_name="license_id", owner="TheoremEntry"
        )
        if self.license_url is not None and not isinstance(self.license_url, str):
            raise ValueError("TheoremEntry.license_url must be a string or None")
        _require_nonempty_str(
            self.content_digest, field_name="content_digest", owner="TheoremEntry"
        )
        if not isinstance(self.metadata, dict):
            raise ValueError("TheoremEntry.metadata must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["source_itp"] = self.source_itp.value
        data["ingested_at"] = _isoformat(self.ingested_at)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TheoremEntry":
        data = dict(data)
        if isinstance(data.get("source_itp"), str):
            data["source_itp"] = ITPKind(data["source_itp"])
        if "ingested_at" in data:
            data["ingested_at"] = _parse_datetime(data["ingested_at"])
        entry = cls(**data)
        entry.validate()
        return entry


# ---------------------------------------------------------------------------
# Corpus manifest
# ---------------------------------------------------------------------------


@dataclass
class CorpusManifest:
    """The versioned collection of declared corpus sources and ingested
    theorem entries.

    ``revision`` is a deterministic digest over the manifest's full content
    (every registered :class:`CorpusSource` and ingested :class:`TheoremEntry`,
    canonically serialized and sorted by id) and changes if and only if the
    manifest's content changes. It is this value that must be carried as
    ``corpus_revision`` on every
    :class:`~ipfs_datasets_py.logic.hammers.models.HammerRequest` and
    :class:`~ipfs_datasets_py.logic.hammers.models.HammerResult` — see
    :func:`verify_hammer_result_corpus`.

    Attributes:
        schema_version: Schema version of this record.
        manifest_id: Caller-assigned identifier for this manifest (e.g.
            ``"itp-hammer-corpus"``); distinct from ``revision``, which is
            content-derived.
        sources: Declared corpus sources, keyed by ``corpus_id``.
        entries: Ingested theorem entries, keyed by ``theorem_id``.
        created_at: When this manifest was first created.
        metadata: Free-form, non-authoritative caller metadata.
    """

    schema_version: str = SCHEMA_VERSION
    manifest_id: str = ""
    sources: Dict[str, CorpusSource] = field(default_factory=dict)
    entries: Dict[str, TheoremEntry] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- revision -----------------------------------------------------

    @property
    def revision(self) -> str:
        """Deterministic content digest of this manifest's full content."""

        payload = {
            "sources": {
                corpus_id: source.to_dict()
                for corpus_id, source in sorted(self.sources.items())
            },
            "entries": {
                theorem_id: entry._revision_payload()
                for theorem_id, entry in sorted(self.entries.items())
            },
        }
        return compute_content_digest(payload)

    # -- mutation -------------------------------------------------------

    def register_source(self, source: CorpusSource) -> CorpusSource:
        """Declare a corpus source that theorems may subsequently be
        ingested against.

        Re-registering the same ``corpus_id`` with byte-identical metadata
        is an idempotent no-op. Re-registering it with different metadata
        (a different ``version_ref``, ``license_id``, ``source_itp``, ...)
        raises :class:`CorpusSourceConflictError`, since that would silently
        change the provenance of every theorem already ingested under that
        corpus.

        Args:
            source: The :class:`CorpusSource` to register.

        Returns:
            The registered (or already-identical, previously registered)
            :class:`CorpusSource`.

        Raises:
            CorpusSourceConflictError: If ``source.corpus_id`` is already
                registered with different metadata.
        """

        if not isinstance(source, CorpusSource):
            raise ValueError("CorpusManifest.register_source requires a CorpusSource")
        source.validate()

        existing = self.sources.get(source.corpus_id)
        if existing is not None and existing.to_dict() != source.to_dict():
            raise CorpusSourceConflictError(
                f"corpus_id {source.corpus_id!r} is already registered with different "
                f"metadata (existing={existing.to_dict()!r}, new={source.to_dict()!r})"
            )

        self.sources[source.corpus_id] = source
        return source

    def add_theorem(
        self,
        *,
        theorem_id: str,
        corpus_id: str,
        statement: str,
        source_itp: Optional[ITPKind] = None,
        imports: Optional[Iterable[str]] = None,
        license_id: Optional[str] = None,
        license_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TheoremEntry:
        """Ingest one theorem/premise into the manifest.

        Args:
            theorem_id: Stable identity of the theorem within the manifest.
            corpus_id: The already-registered :class:`CorpusSource` this
                theorem comes from.
            statement: The raw statement text, as authored.
            source_itp: ITP the statement is native to; defaults to the
                owning corpus's ``source_itp`` and, if given explicitly,
                must match it.
            imports: Module/theory/file dependencies the statement requires.
            license_id: Overrides the owning corpus's default ``license_id``
                for this specific theorem.
            license_url: Overrides the owning corpus's default
                ``license_url`` for this specific theorem.
            metadata: Free-form, non-authoritative caller metadata.

        Returns:
            The ingested (or, for an idempotent re-ingestion, the existing)
            :class:`TheoremEntry`.

        Raises:
            UndeclaredCorpusSourceError: If ``corpus_id`` has not been
                registered via :meth:`register_source`.
            DuplicateTheoremIdentityError: If ``theorem_id`` already exists
                in the manifest with a different normalized-statement
                digest, source ITP, or corpus.
        """

        source = self.sources.get(corpus_id)
        if source is None:
            raise UndeclaredCorpusSourceError(
                f"cannot ingest theorem_id {theorem_id!r}: corpus_id {corpus_id!r} has not "
                "been declared via CorpusManifest.register_source"
            )

        resolved_itp = source_itp if source_itp is not None else source.source_itp
        if resolved_itp != source.source_itp:
            raise ValueError(
                f"theorem_id {theorem_id!r} declares source_itp={resolved_itp!r} but "
                f"corpus {corpus_id!r} is registered as source_itp={source.source_itp!r}"
            )

        resolved_license_id = license_id if license_id is not None else source.license_id
        resolved_license_url = (
            license_url if license_url is not None else source.license_url
        )

        candidate = TheoremEntry.create(
            theorem_id=theorem_id,
            corpus_id=corpus_id,
            source_itp=resolved_itp,
            statement=statement,
            imports=imports,
            license_id=resolved_license_id,
            license_url=resolved_license_url,
            metadata=metadata,
        )

        existing = self.entries.get(theorem_id)
        if existing is not None:
            if (
                existing.statement_digest != candidate.statement_digest
                or existing.corpus_id != candidate.corpus_id
                or existing.source_itp != candidate.source_itp
            ):
                raise DuplicateTheoremIdentityError(
                    f"theorem_id {theorem_id!r} already exists with a different "
                    f"statement/corpus/ITP (existing statement_digest="
                    f"{existing.statement_digest!r} corpus_id={existing.corpus_id!r} "
                    f"source_itp={existing.source_itp.value!r}; new statement_digest="
                    f"{candidate.statement_digest!r} corpus_id={candidate.corpus_id!r} "
                    f"source_itp={candidate.source_itp.value!r})"
                )
            # Idempotent re-ingestion of an unchanged theorem: keep the
            # original record (preserves its original ingested_at) rather
            # than silently replacing it.
            return existing

        self.entries[theorem_id] = candidate
        return candidate

    # -- lookup -----------------------------------------------------------

    def get_theorem(self, theorem_id: str) -> TheoremEntry:
        try:
            return self.entries[theorem_id]
        except KeyError as exc:
            raise KeyError(f"no theorem ingested with theorem_id {theorem_id!r}") from exc

    def get_source(self, corpus_id: str) -> CorpusSource:
        try:
            return self.sources[corpus_id]
        except KeyError as exc:
            raise KeyError(f"no corpus source registered with corpus_id {corpus_id!r}") from exc

    def iter_theorems(self) -> List[TheoremEntry]:
        """Return all ingested theorems, sorted by ``theorem_id`` for a
        stable, reproducible iteration order."""

        return [self.entries[key] for key in sorted(self.entries)]

    def theorems_for_corpus(self, corpus_id: str) -> List[TheoremEntry]:
        return [entry for entry in self.iter_theorems() if entry.corpus_id == corpus_id]

    # -- validation / serialization ----------------------------------------

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="CorpusManifest")
        _require_nonempty_str(
            self.manifest_id, field_name="manifest_id", owner="CorpusManifest"
        )
        if not isinstance(self.sources, dict):
            raise ValueError("CorpusManifest.sources must be a dict")
        for corpus_id, source in self.sources.items():
            if not isinstance(source, CorpusSource):
                raise ValueError("CorpusManifest.sources values must be CorpusSource")
            if source.corpus_id != corpus_id:
                raise ValueError(
                    f"CorpusManifest.sources key {corpus_id!r} does not match "
                    f"CorpusSource.corpus_id {source.corpus_id!r}"
                )
            source.validate()

        if not isinstance(self.entries, dict):
            raise ValueError("CorpusManifest.entries must be a dict")
        for theorem_id, entry in self.entries.items():
            if not isinstance(entry, TheoremEntry):
                raise ValueError("CorpusManifest.entries values must be TheoremEntry")
            if entry.theorem_id != theorem_id:
                raise ValueError(
                    f"CorpusManifest.entries key {theorem_id!r} does not match "
                    f"TheoremEntry.theorem_id {entry.theorem_id!r}"
                )
            entry.validate()
            if entry.corpus_id not in self.sources:
                raise ValueError(
                    f"theorem_id {theorem_id!r} references undeclared corpus_id "
                    f"{entry.corpus_id!r}"
                )

        if not isinstance(self.metadata, dict):
            raise ValueError("CorpusManifest.metadata must be a dict")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "revision": self.revision,
            "sources": {
                corpus_id: source.to_dict() for corpus_id, source in self.sources.items()
            },
            "entries": {
                theorem_id: entry.to_dict() for theorem_id, entry in self.entries.items()
            },
            "created_at": _isoformat(self.created_at),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorpusManifest":
        data = dict(data)
        data.pop("revision", None)  # derived, never stored as authoritative state
        sources_data = data.pop("sources", {}) or {}
        entries_data = data.pop("entries", {}) or {}
        if "created_at" in data:
            data["created_at"] = _parse_datetime(data["created_at"])

        manifest = cls(**data)
        manifest.sources = {
            corpus_id: CorpusSource.from_dict(source)
            for corpus_id, source in sources_data.items()
        }
        manifest.entries = {
            theorem_id: TheoremEntry.from_dict(entry)
            for theorem_id, entry in entries_data.items()
        }
        manifest.validate()
        return manifest

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "CorpusManifest":
        return cls.from_dict(json.loads(text))

    def save(self, path: str) -> None:
        """Persist this manifest as a versioned JSON document at ``path``."""

        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "CorpusManifest":
        """Load a manifest previously written by :meth:`save`."""

        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_json(handle.read())


# ---------------------------------------------------------------------------
# Integration with the HammerResult trust contract (HAMMER-001)
# ---------------------------------------------------------------------------


def verify_hammer_result_corpus(result: Any, manifest: CorpusManifest) -> None:
    """Verify that a ``HammerResult`` is bound to a specific corpus manifest
    snapshot.

    This is what "retain the corpus revision in every hammer result" is
    checked against operationally: every hammer result must declare the
    exact corpus revision its premises were drawn from, and every premise it
    cites must actually exist in that revision with a matching identity.

    Args:
        result: A ``HammerResult`` (imported lazily by callers from
            ``ipfs_datasets_py.logic.hammers.models`` to avoid a hard import
            cycle; duck-typed here on ``corpus_revision``, ``request``, and
            ``premises``).
        manifest: The :class:`CorpusManifest` snapshot to verify against.

    Raises:
        CorpusRevisionMismatchError: If ``result.corpus_revision`` (or its
            ``request.corpus_revision``) does not match ``manifest.revision``,
            or if any cited premise does not exist in the manifest.
    """

    manifest_revision = manifest.revision

    result_revision = getattr(result, "corpus_revision", None)
    if result_revision != manifest_revision:
        raise CorpusRevisionMismatchError(
            f"HammerResult.corpus_revision {result_revision!r} does not match manifest "
            f"revision {manifest_revision!r}"
        )

    request = getattr(result, "request", None)
    request_revision = getattr(request, "corpus_revision", None) if request is not None else None
    if request is not None and request_revision != manifest_revision:
        raise CorpusRevisionMismatchError(
            f"HammerResult.request.corpus_revision {request_revision!r} does not match "
            f"manifest revision {manifest_revision!r}"
        )

    for premise in getattr(result, "premises", []) or []:
        premise_revision = getattr(premise, "corpus_revision", None)
        if premise_revision != manifest_revision:
            raise CorpusRevisionMismatchError(
                f"premise {getattr(premise, 'premise_id', '<unknown>')!r} has "
                f"corpus_revision {premise_revision!r}, expected {manifest_revision!r}"
            )
        premise_id = getattr(premise, "premise_id", None)
        if premise_id not in manifest.entries:
            raise CorpusRevisionMismatchError(
                f"premise {premise_id!r} does not exist in corpus manifest revision "
                f"{manifest_revision!r}"
            )
