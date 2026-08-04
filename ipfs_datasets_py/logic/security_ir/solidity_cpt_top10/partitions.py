"""Lineage-safe partitions and retrieval fences for Solidity CPT Top-10.

Connected-component grouping always precedes partition assignment.  Groups form
from exact and near-duplicate content, repository/source family, normalized
path history, deployment address, fork/import lineage, and generated-code
family.  Individual rows from the upstream single ``train`` split are never
randomly divided; whole connected groups are assigned deterministically.

Persisted manifests carry hashed bounded grouping evidence only.  Raw Solidity
bodies never survive into partition wire forms.  Evaluation retrieval is fenced
to one partition, source snapshot, and family scope; missing evidence, overlap,
drift, or attempted leakage fails closed.

This module performs no network access, compilation, training, or publication.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlparse

from .release_policy import (
    SOLIDITY_CPT_DATASET_ID,
    SOLIDITY_CPT_REVISION,
    SOLIDITY_CPT_SPLIT,
)


PARTITION_MANIFEST_SCHEMA_VERSION: Final = "solidity-cpt-partition-manifest/v1"
PARTITION_EXAMPLE_SCHEMA_VERSION: Final = "solidity-cpt-partition-example/v1"
RETRIEVAL_FENCE_SCHEMA_VERSION: Final = "solidity-cpt-retrieval-fence/v1"
DUPLICATE_FAMILY_SCHEMA_VERSION: Final = "solidity-cpt-duplicate-family/v1"
PARTITION_CONFIG_SCHEMA_VERSION: Final = "solidity-cpt-partition-config/v1"

TRAIN_PARTITION: Final = "train"
VALIDATION_PARTITION: Final = "validation"
TEST_PARTITION: Final = "test"
HELD_OUT_PARTITION: Final = "held_out"
ADVERSARIAL_PARTITION: Final = "adversarial"
SOLIDITY_PARTITIONS: Final = (
    TRAIN_PARTITION,
    VALIDATION_PARTITION,
    TEST_PARTITION,
    HELD_OUT_PARTITION,
    ADVERSARIAL_PARTITION,
)

# Upstream HF corpus pin is a single train split; local partitions are derived.
UPSTREAM_SOURCE_SPLIT: Final = SOLIDITY_CPT_SPLIT

_MAX_GROUP_VALUES = 256
_MAX_VALUE_CHARS = 1024
_MAX_SHINGLES = 256
_MAX_SAMPLE_ID_CHARS = 512
_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_SHINGLE_RE = re.compile(r"^[0-9a-f]{16}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_METADATA_KEYS: Final = frozenset(
    {
        "near_duplicate_jaccard_threshold",
        "seed",
        "source_dataset_id",
        "source_revision",
        "source_split",
        "policy_digest",
        "source_snapshot_cid",
        "upstream_split_policy",
    }
)

# Marketplace / explorer catalogs are too coarse to form a single connected
# component on their own (they would collapse the entire HF train split).
_COARSE_SOURCE_CATALOGS: Final = frozenset(
    {
        "etherscan",
        "sourcify",
        "bscscan",
        "polygonscan",
        "arbiscan",
        "optimistic.etherscan",
        "snowtrace",
        "ftmscan",
        "gnosisscan",
        "basescan",
        "lineascan",
        "scrollscan",
        "verified_source",
        "unknown",
    }
)


class SolidityPartitionError(ValueError):
    """Base class for malformed partition contracts."""


class SolidityPartitionLeakageError(SolidityPartitionError):
    """Raised when a connected group crosses partition boundaries."""

    def __init__(
        self, message: str, result: "SolidityPartitionGuardResult"
    ) -> None:
        super().__init__(message)
        self.result = result


class SolidityRetrievalFenceError(SolidityPartitionError):
    """Raised when retrieval would cross a partition, snapshot, or family fence."""

    def __init__(
        self, message: str, result: "SolidityRetrievalFenceResult"
    ) -> None:
        super().__init__(message)
        self.result = result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _get(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray)
    ):
        values = tuple(value)
    else:
        values = (value,)
    result = tuple(sorted({_text(item) for item in values if _text(item)}))
    if len(result) > _MAX_GROUP_VALUES:
        raise SolidityPartitionError(
            f"partition grouping field exceeds {_MAX_GROUP_VALUES} values"
        )
    if any(len(item) > _MAX_VALUE_CHARS or "\x00" in item for item in result):
        raise SolidityPartitionError(
            "partition grouping values must be bounded text"
        )
    return result


def _wire_values(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise SolidityPartitionError(f"{field_name} must be a sequence of strings")
    if any(not isinstance(item, str) for item in value):
        raise SolidityPartitionError(f"{field_name} must contain only strings")
    return _values(value)


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _content_digest(value: str) -> str:
    return _digest({"normalized_content": _normalized_text(value)})


def _hashed_shingles(value: str) -> tuple[str, ...]:
    """Return bounded non-plaintext token hashes for near-duplicate comparison."""

    tokens = re.findall(r"[\w]+", _normalized_text(value), flags=re.UNICODE)
    if not tokens:
        return ()
    hashes = sorted(
        {
            hashlib.blake2s(
                token.encode("utf-8"),
                digest_size=8,
                person=b"solcsplt",
            ).hexdigest()
            for token in tokens
        }
    )
    if len(hashes) <= _MAX_SHINGLES:
        return tuple(hashes)
    return tuple(hashes[:_MAX_SHINGLES])


def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set = frozenset(left)
    right_set = frozenset(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _normalize_digest(value: str) -> str:
    match = _SHA256_RE.fullmatch(_text(value).casefold())
    return f"sha256:{match.group(1)}" if match else ""


def _normalize_address(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if not _ADDRESS_RE.fullmatch(text):
        # Keep non-EVM or partial address hints as case-folded opaque tokens.
        if len(text) > _MAX_VALUE_CHARS or "\x00" in text:
            raise SolidityPartitionError("address must be bounded text")
        return text.casefold()
    return text.casefold()


def _normalize_path(value: Any) -> str:
    text = _text(value).replace("\\", "/")
    if not text:
        return ""
    parts = [
        part
        for part in text.split("/")
        if part and part not in {".", ".."}
    ]
    normalized = "/".join(parts).casefold()
    if len(normalized) > _MAX_VALUE_CHARS or "\x00" in normalized:
        raise SolidityPartitionError("normalized path must be bounded text")
    return normalized


def _repository_key(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if "://" in text or text.startswith("hf://"):
        parsed = urlparse(text)
        host = parsed.netloc.casefold()
        parts = tuple(part for part in parsed.path.split("/") if part)
        if host in {
            "github.com",
            "www.github.com",
            "gitlab.com",
            "www.gitlab.com",
        }:
            if len(parts) >= 2:
                return (
                    f"{host.removeprefix('www.')}/"
                    f"{parts[0].casefold()}/{parts[1].casefold()}"
                )
        if parsed.scheme == "hf" and host == "datasets":
            dataset = parsed.path.split("@", 1)[0].strip("/")
            return f"hf/datasets/{dataset.casefold()}" if dataset else ""
        if host:
            return host
    return text.casefold()


def _extract_import_lineage(text: str) -> tuple[str, ...]:
    """Hash import/path targets from Solidity source without retaining bodies."""

    if not text:
        return ()
    targets: set[str] = set()
    for match in re.finditer(
        r"""import\s+(?:\{[^}]*\}\s+from\s+)?["']([^"']+)["']""",
        text,
        flags=re.IGNORECASE,
    ):
        target = _normalize_path(match.group(1))
        if target:
            targets.add(
                hashlib.blake2s(
                    target.encode("utf-8"),
                    digest_size=8,
                    person=b"solcimp",
                ).hexdigest()
            )
    for match in re.finditer(
        r"""(?:pragma\s+solidity|//\s*@?fork(?:ed)?(?:-from)?)\s*[:=]?\s*([^\s;]+)""",
        text,
        flags=re.IGNORECASE,
    ):
        # pragma versions and explicit fork markers become opaque lineage tokens.
        token = _text(match.group(1)).casefold()
        if token and len(token) <= _MAX_VALUE_CHARS:
            targets.add(
                hashlib.blake2s(
                    token.encode("utf-8"),
                    digest_size=8,
                    person=b"solcfork",
                ).hexdigest()
            )
    ordered = tuple(sorted(targets))
    if len(ordered) > _MAX_GROUP_VALUES:
        return ordered[:_MAX_GROUP_VALUES]
    return ordered


def _sample_text(sample: Any) -> str:
    for name in (
        "near_duplicate_text",
        "normalized_text",
        "source_text",
        "source_body",
        "body",
        "text",
        "content",
    ):
        value = _get(sample, name, default=None)
        if isinstance(value, str) and value:
            return value
        if value is not None and hasattr(value, "text"):
            nested = getattr(value, "text")
            if isinstance(nested, str) and nested:
                return nested
    row = _get(sample, "row", default=None)
    if row is not None:
        return _sample_text(row)
    return ""


def _sample_id_from(sample: Any) -> str:
    for name in (
        "sample_id",
        "row_id",
        "example_id",
        "document_id",
        "source_row_id",
    ):
        value = _text(_get(sample, name, default=""))
        if value:
            return value
    row_index = _get(sample, "row_index", default=None)
    if row_index is not None and type(row_index) is int:
        return f"row:{row_index}"
    raise SolidityPartitionError(
        "sample requires sample_id, row_id, or integer row_index"
    )


@dataclass(frozen=True, slots=True)
class DuplicateFamily:
    """Bounded evidence that several samples share one leakage group signal."""

    family_id: str
    kind: str
    sample_ids: tuple[str, ...]
    evidence_digest: str = ""
    schema_version: str = DUPLICATE_FAMILY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DUPLICATE_FAMILY_SCHEMA_VERSION:
            raise SolidityPartitionError("unsupported duplicate family schema")
        family_id = _text(self.family_id)
        kind = _text(self.kind)
        if not family_id or len(family_id) > _MAX_VALUE_CHARS or "\x00" in family_id:
            raise SolidityPartitionError("family_id must be bounded non-empty text")
        if not kind or len(kind) > 128 or "\x00" in kind:
            raise SolidityPartitionError("duplicate family kind must be bounded text")
        sample_ids = tuple(sorted(set(_values(self.sample_ids))))
        if len(sample_ids) < 2:
            raise SolidityPartitionError(
                "duplicate family requires at least two sample ids"
            )
        payload = {
            "family_id": family_id,
            "kind": kind,
            "sample_ids": list(sample_ids),
            "schema_version": self.schema_version,
        }
        computed = _digest(payload)
        if self.evidence_digest and self.evidence_digest != computed:
            raise SolidityPartitionError(
                "duplicate family evidence_digest does not match rehash"
            )
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "sample_ids", sample_ids)
        object.__setattr__(self, "evidence_digest", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_digest": self.evidence_digest,
            "family_id": self.family_id,
            "kind": self.kind,
            "sample_ids": list(self.sample_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DuplicateFamily":
        if not isinstance(value, Mapping):
            raise SolidityPartitionError("duplicate family must be a mapping")
        return cls(
            family_id=value.get("family_id", ""),
            kind=value.get("kind", ""),
            sample_ids=_wire_values(value.get("sample_ids", ()), "sample_ids"),
            evidence_digest=_text(value.get("evidence_digest", "")),
            schema_version=value.get(
                "schema_version", DUPLICATE_FAMILY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SolidityPartitionExample:
    """Source-free grouping metadata for one Solidity corpus row."""

    sample_id: str
    content_digests: tuple[str, ...] = ()
    repository_ids: tuple[str, ...] = ()
    source_family_ids: tuple[str, ...] = ()
    normalized_paths: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    fork_lineage_ids: tuple[str, ...] = ()
    import_lineage_ids: tuple[str, ...] = ()
    generated_code_family_ids: tuple[str, ...] = ()
    duplicate_family_ids: tuple[str, ...] = ()
    near_duplicate_signature: tuple[str, ...] = ()
    source_snapshot_cid: str = ""
    graph_snapshot_id: str = ""
    embedding_snapshot_id: str = ""
    domain: str = ""
    adversarial: bool = False
    held_out: bool = False
    schema_version: str = PARTITION_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sample_id = _text(self.sample_id)
        if (
            not sample_id
            or len(sample_id) > _MAX_SAMPLE_ID_CHARS
            or "\x00" in sample_id
        ):
            raise SolidityPartitionError(
                "sample_id must be bounded non-empty text"
            )
        object.__setattr__(self, "sample_id", sample_id)
        object.__setattr__(self, "domain", _text(self.domain).casefold())
        for field_name in (
            "repository_ids",
            "source_family_ids",
            "normalized_paths",
            "fork_lineage_ids",
            "import_lineage_ids",
            "generated_code_family_ids",
            "duplicate_family_ids",
        ):
            object.__setattr__(
                self, field_name, _values(getattr(self, field_name))
            )
        digests = tuple(
            digest
            for digest in (
                _normalize_digest(item) for item in _values(self.content_digests)
            )
            if digest
        )
        if len(digests) != len(_values(self.content_digests)):
            raise SolidityPartitionError(
                "content_digests must contain lowercase SHA-256 values"
            )
        object.__setattr__(self, "content_digests", tuple(sorted(set(digests))))
        addresses = tuple(
            address
            for address in (
                _normalize_address(item) for item in _values(self.addresses)
            )
            if address
        )
        object.__setattr__(self, "addresses", tuple(sorted(set(addresses))))
        paths = tuple(
            path
            for path in (
                _normalize_path(item) for item in _values(self.normalized_paths)
            )
            if path
        )
        object.__setattr__(self, "normalized_paths", tuple(sorted(set(paths))))
        object.__setattr__(
            self,
            "near_duplicate_signature",
            tuple(sorted(set(_values(self.near_duplicate_signature)))),
        )
        if any(
            not _SHINGLE_RE.fullmatch(item)
            for item in self.near_duplicate_signature
        ):
            raise SolidityPartitionError(
                "near_duplicate_signature must contain hashed token values"
            )
        for field_name in (
            "source_snapshot_cid",
            "graph_snapshot_id",
            "embedding_snapshot_id",
        ):
            value = _text(getattr(self, field_name))
            if len(value) > _MAX_VALUE_CHARS or "\x00" in value:
                raise SolidityPartitionError(f"{field_name} must be bounded text")
            object.__setattr__(self, field_name, value)
        if type(self.adversarial) is not bool:
            raise SolidityPartitionError("adversarial must be a boolean")
        if type(self.held_out) is not bool:
            raise SolidityPartitionError("held_out must be a boolean")
        if self.schema_version != PARTITION_EXAMPLE_SCHEMA_VERSION:
            raise SolidityPartitionError(
                "unsupported partition example schema"
            )
        if not self.has_grouping_evidence():
            raise SolidityPartitionError(
                f"sample {sample_id!r} is missing required grouping evidence"
            )

    def has_grouping_evidence(self) -> bool:
        return bool(
            self.content_digests
            or self.repository_ids
            or self.source_family_ids
            or self.normalized_paths
            or self.addresses
            or self.fork_lineage_ids
            or self.import_lineage_ids
            or self.generated_code_family_ids
            or self.duplicate_family_ids
            or self.near_duplicate_signature
        )

    def lineage_repository_keys(self) -> tuple[str, ...]:
        """Repository keys specific enough to form connected components."""

        return tuple(
            key
            for key in self.repository_ids
            if key and key.casefold() not in _COARSE_SOURCE_CATALOGS
        )

    def lineage_source_family_keys(self) -> tuple[str, ...]:
        """Source-family keys that are not coarse explorer catalogs."""

        return tuple(
            key
            for key in self.source_family_ids
            if key and key.casefold() not in _COARSE_SOURCE_CATALOGS
        )

    def lineage_path_keys(self) -> tuple[str, ...]:
        """Path history keys scoped by repository/source when available."""

        scopes = self.lineage_repository_keys() or self.lineage_source_family_keys()
        if not self.normalized_paths:
            return ()
        if not scopes:
            # Bare common filenames (e.g. Token.sol) must not link unrelated
            # projects; require a project-shaped path with at least two segments.
            return tuple(
                path for path in self.normalized_paths if "/" in path
            )
        keys: list[str] = []
        for scope in scopes:
            for path in self.normalized_paths:
                keys.append(f"{scope}\x1f{path}")
        return tuple(sorted(set(keys)))

    def lineage_import_keys(self) -> tuple[str, ...]:
        """Explicit import lineage only (auto-extracted 16-hex tokens excluded)."""

        return tuple(
            key
            for key in self.import_lineage_ids
            if not _SHINGLE_RE.fullmatch(key)
        )

    def lineage_fork_keys(self) -> tuple[str, ...]:
        """Explicit fork lineage only (auto-extracted 16-hex tokens excluded)."""

        return tuple(
            key
            for key in self.fork_lineage_ids
            if not _SHINGLE_RE.fullmatch(key)
        )

    @classmethod
    def from_sample(
        cls, sample: Any, **overrides: Any
    ) -> "SolidityPartitionExample":
        """Project a row, adapted row, or mapping into source-free metadata."""

        sample_id = _sample_id_from(sample)
        text = _sample_text(sample)
        body_sha = _text(
            _get(
                sample,
                "source_body_sha256",
                "content_sha256",
                "body_sha256",
                default="",
            )
        )
        row = _get(sample, "row", default=None)
        if row is not None:
            body_sha = body_sha or _text(
                _get(row, "source_body_sha256", "content_sha256", default="")
            )
            if not sample_id or sample_id.startswith("row:"):
                try:
                    sample_id = _sample_id_from(row)
                except SolidityPartitionError:
                    pass

        content_digests = list(
            _values(
                _get(
                    sample,
                    "content_digests",
                    "content_sha256",
                    default=(),
                )
            )
        )
        if body_sha:
            content_digests.append(body_sha)
        if text:
            content_digests.append(_content_digest(text))

        source_value = _text(
            _get(sample, "source", "source_family", "source_name", default="")
        )
        if not source_value and row is not None:
            source_value = _text(_get(row, "source", default=""))

        repository_ids = list(
            _values(
                _get(
                    sample,
                    "repository_ids",
                    "repository_id",
                    "repository",
                    default=(),
                )
            )
        )
        repo_from_uri = _repository_key(
            _get(sample, "source_uri", "repository_uri", "url", default="")
        )
        if repo_from_uri:
            repository_ids.append(repo_from_uri)
        if source_value and source_value not in repository_ids:
            # etherscan/sourcify/etc. are coarse source-family signals.
            pass

        path_value = _text(_get(sample, "path", "source_path", default=""))
        if not path_value and row is not None:
            path_value = _text(_get(row, "path", default=""))
        paths = list(
            _values(_get(sample, "normalized_paths", "path_history", default=()))
        )
        if path_value:
            paths.append(path_value)

        address_value = _text(
            _get(sample, "address", "contract_address", default="")
        )
        if not address_value and row is not None:
            address_value = _text(_get(row, "address", default=""))
        addresses = list(
            _values(_get(sample, "addresses", "contract_addresses", default=()))
        )
        if address_value:
            addresses.append(address_value)

        fork_ids = list(
            _values(
                _get(
                    sample,
                    "fork_lineage_ids",
                    "fork_family_ids",
                    "fork_family_id",
                    default=(),
                )
            )
        )
        import_ids = list(
            _values(
                _get(
                    sample,
                    "import_lineage_ids",
                    "import_family_ids",
                    "import_targets",
                    default=(),
                )
            )
        )
        # Auto-extracted import/fork tokens are retained as bounded evidence on
        # the example, but only *explicit* lineage IDs participate in union-find
        # grouping (shared OpenZeppelin import paths would otherwise collapse
        # nearly every contract into one component).
        extracted = _extract_import_lineage(text)
        evidence_import_ids = list(import_ids)
        evidence_fork_ids = list(fork_ids)
        if extracted:
            evidence_import_ids.extend(extracted)
            if not fork_ids:
                evidence_fork_ids.extend(extracted)

        generated = list(
            _values(
                _get(
                    sample,
                    "generated_code_family_ids",
                    "generated_code_family_id",
                    "generation_family_id",
                    "generation_family",
                    default=(),
                )
            )
        )
        if not generated:
            prompt_hash = _text(_get(sample, "prompt_hash", default=""))
            model_hash = _text(_get(sample, "model_hash", default=""))
            if prompt_hash or model_hash:
                generated.append(
                    _digest(
                        {"model_hash": model_hash, "prompt_hash": prompt_hash}
                    )
                )

        values: dict[str, Any] = {
            "sample_id": sample_id,
            "content_digests": tuple(content_digests),
            "repository_ids": tuple(repository_ids),
            "source_family_ids": _values(
                _get(
                    sample,
                    "source_family_ids",
                    "source_family_id",
                    default=(source_value,) if source_value else (),
                )
            )
            or ((source_value,) if source_value else ()),
            "normalized_paths": tuple(paths),
            "addresses": tuple(addresses),
            "fork_lineage_ids": tuple(evidence_fork_ids),
            "import_lineage_ids": tuple(evidence_import_ids),
            "generated_code_family_ids": tuple(generated),
            "duplicate_family_ids": _values(
                _get(
                    sample,
                    "duplicate_family_ids",
                    "duplicate_family_id",
                    "near_duplicate_cluster_id",
                    "dedup_cluster_id",
                    default=(),
                )
            ),
            "near_duplicate_signature": _hashed_shingles(text),
            "source_snapshot_cid": _text(
                _get(
                    sample,
                    "source_snapshot_cid",
                    "snapshot_cid",
                    default="",
                )
            )
            or (
                _text(_get(row, "source_snapshot_cid", default=""))
                if row is not None
                else ""
            ),
            "graph_snapshot_id": _text(
                _get(sample, "graph_snapshot_id", default="")
            ),
            "embedding_snapshot_id": _text(
                _get(sample, "embedding_snapshot_id", default="")
            ),
            "domain": _text(_get(sample, "domain", default="")),
            "adversarial": bool(_get(sample, "adversarial", default=False)),
            "held_out": bool(
                _get(sample, "held_out", "is_held_out", default=False)
            ),
        }
        values.update(overrides)
        return cls(**values)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityPartitionExample":
        allowed = {
            "addresses",
            "adversarial",
            "content_digests",
            "domain",
            "duplicate_family_ids",
            "embedding_snapshot_id",
            "fork_lineage_ids",
            "generated_code_family_ids",
            "graph_snapshot_id",
            "held_out",
            "import_lineage_ids",
            "near_duplicate_signature",
            "normalized_paths",
            "repository_ids",
            "sample_id",
            "schema_version",
            "source_family_ids",
            "source_snapshot_cid",
        }
        if not isinstance(value, Mapping):
            raise SolidityPartitionError("partition example must be a mapping")
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SolidityPartitionError(
                "unknown partition example fields: " + ", ".join(unknown)
            )
        return cls(
            sample_id=value.get("sample_id", ""),
            content_digests=_wire_values(
                value.get("content_digests", ()), "content_digests"
            ),
            repository_ids=_wire_values(
                value.get("repository_ids", ()), "repository_ids"
            ),
            source_family_ids=_wire_values(
                value.get("source_family_ids", ()), "source_family_ids"
            ),
            normalized_paths=_wire_values(
                value.get("normalized_paths", ()), "normalized_paths"
            ),
            addresses=_wire_values(value.get("addresses", ()), "addresses"),
            fork_lineage_ids=_wire_values(
                value.get("fork_lineage_ids", ()), "fork_lineage_ids"
            ),
            import_lineage_ids=_wire_values(
                value.get("import_lineage_ids", ()), "import_lineage_ids"
            ),
            generated_code_family_ids=_wire_values(
                value.get("generated_code_family_ids", ()),
                "generated_code_family_ids",
            ),
            duplicate_family_ids=_wire_values(
                value.get("duplicate_family_ids", ()), "duplicate_family_ids"
            ),
            near_duplicate_signature=_wire_values(
                value.get("near_duplicate_signature", ()),
                "near_duplicate_signature",
            ),
            source_snapshot_cid=value.get("source_snapshot_cid", ""),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            embedding_snapshot_id=value.get("embedding_snapshot_id", ""),
            domain=value.get("domain", ""),
            adversarial=bool(value.get("adversarial", False)),
            held_out=bool(value.get("held_out", False)),
            schema_version=value.get(
                "schema_version", PARTITION_EXAMPLE_SCHEMA_VERSION
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "addresses": list(self.addresses),
            "adversarial": self.adversarial,
            "content_digests": list(self.content_digests),
            "domain": self.domain,
            "duplicate_family_ids": list(self.duplicate_family_ids),
            "embedding_snapshot_id": self.embedding_snapshot_id,
            "fork_lineage_ids": list(self.fork_lineage_ids),
            "generated_code_family_ids": list(self.generated_code_family_ids),
            "graph_snapshot_id": self.graph_snapshot_id,
            "held_out": self.held_out,
            "import_lineage_ids": list(self.import_lineage_ids),
            "near_duplicate_signature": list(self.near_duplicate_signature),
            "normalized_paths": list(self.normalized_paths),
            "repository_ids": list(self.repository_ids),
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "source_family_ids": list(self.source_family_ids),
            "source_snapshot_cid": self.source_snapshot_cid,
        }


@dataclass(frozen=True, slots=True)
class SolidityPartitionConfig:
    """Deterministic, CID-bound policy for connected-component assignment.

    Ratios apply only after connected-component grouping.  The upstream HF
    ``train`` split is never randomly subdivided row-by-row.
    """

    seed: str = "solidity-cpt-partitions"
    train_ratio: float = 0.70
    validation_ratio: float = 0.15
    test_ratio: float = 0.15
    near_duplicate_jaccard_threshold: float = 0.80
    held_out_domains: tuple[str, ...] = ()
    held_out_source_families: tuple[str, ...] = ()
    held_out_addresses: tuple[str, ...] = ()
    adversarial_family_ids: tuple[str, ...] = ()
    source_dataset_id: str = SOLIDITY_CPT_DATASET_ID
    source_revision: str = SOLIDITY_CPT_REVISION
    source_split: str = UPSTREAM_SOURCE_SPLIT
    policy_digest: str = ""
    source_snapshot_cid: str = ""
    schema_version: str = PARTITION_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PARTITION_CONFIG_SCHEMA_VERSION:
            raise SolidityPartitionError("unsupported partition config schema")
        ratios = (self.train_ratio, self.validation_ratio, self.test_ratio)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in ratios
        ):
            raise SolidityPartitionError(
                "partition ratios must be finite and non-negative"
            )
        if sum(float(value) for value in ratios) <= 0.0:
            raise SolidityPartitionError(
                "at least one primary partition ratio must be positive"
            )
        threshold = float(self.near_duplicate_jaccard_threshold)
        if not 0.0 < threshold <= 1.0 or not math.isfinite(threshold):
            raise SolidityPartitionError(
                "near_duplicate_jaccard_threshold must be in (0, 1]"
            )
        object.__setattr__(self, "seed", _text(self.seed))
        if not self.seed or len(self.seed) > _MAX_VALUE_CHARS or "\x00" in self.seed:
            raise SolidityPartitionError("seed must be bounded non-empty text")
        object.__setattr__(
            self,
            "held_out_domains",
            tuple(item.casefold() for item in _values(self.held_out_domains)),
        )
        object.__setattr__(
            self,
            "held_out_source_families",
            tuple(
                item.casefold()
                for item in _values(self.held_out_source_families)
            ),
        )
        object.__setattr__(
            self,
            "held_out_addresses",
            tuple(
                _normalize_address(item)
                for item in _values(self.held_out_addresses)
                if _normalize_address(item)
            ),
        )
        object.__setattr__(
            self,
            "adversarial_family_ids",
            _values(self.adversarial_family_ids),
        )
        object.__setattr__(
            self, "near_duplicate_jaccard_threshold", threshold
        )
        for field_name, expected in (
            ("source_dataset_id", SOLIDITY_CPT_DATASET_ID),
            ("source_revision", SOLIDITY_CPT_REVISION),
            ("source_split", UPSTREAM_SOURCE_SPLIT),
        ):
            value = _text(getattr(self, field_name))
            if value != expected:
                raise SolidityPartitionError(
                    f"{field_name} must match the pinned Solidity CPT source "
                    f"({expected!r}); got {value!r}"
                )
            object.__setattr__(self, field_name, value)
        policy = _text(self.policy_digest)
        if policy and (
            len(policy) > _MAX_VALUE_CHARS or "\x00" in policy
        ):
            raise SolidityPartitionError("policy_digest must be bounded text")
        object.__setattr__(self, "policy_digest", policy)
        snapshot = _text(self.source_snapshot_cid)
        if snapshot and (
            len(snapshot) > _MAX_VALUE_CHARS or "\x00" in snapshot
        ):
            raise SolidityPartitionError(
                "source_snapshot_cid must be bounded text"
            )
        object.__setattr__(self, "source_snapshot_cid", snapshot)

    @property
    def digest(self) -> str:
        """CID-style content digest binding ratios, seed, policy, and pin."""

        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversarial_family_ids": list(self.adversarial_family_ids),
            "held_out_addresses": list(self.held_out_addresses),
            "held_out_domains": list(self.held_out_domains),
            "held_out_source_families": list(self.held_out_source_families),
            "near_duplicate_jaccard_threshold": (
                self.near_duplicate_jaccard_threshold
            ),
            "policy_digest": self.policy_digest,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "source_dataset_id": self.source_dataset_id,
            "source_revision": self.source_revision,
            "source_snapshot_cid": self.source_snapshot_cid,
            "source_split": self.source_split,
            "test_ratio": self.test_ratio,
            "train_ratio": self.train_ratio,
            "upstream_split_policy": "never_random_row_split",
            "validation_ratio": self.validation_ratio,
        }


@dataclass(frozen=True, slots=True)
class SolidityLeakageViolation:
    kind: str
    key: str
    partitions: tuple[str, ...]
    sample_ids_by_partition: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sample_ids_by_partition",
            MappingProxyType(
                {
                    key: tuple(value)
                    for key, value in sorted(
                        self.sample_ids_by_partition.items()
                    )
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "partitions": list(self.partitions),
            "sample_ids_by_partition": {
                partition: list(ids)
                for partition, ids in self.sample_ids_by_partition.items()
            },
        }


@dataclass(frozen=True, slots=True)
class SolidityPartitionGuardResult:
    passed: bool
    violations: tuple[SolidityLeakageViolation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True, slots=True)
class SolidityPartitionManifest:
    """Immutable connected-component assignments and hashed grouping evidence."""

    examples: tuple[SolidityPartitionExample, ...]
    assignments: Mapping[str, str]
    config_digest: str
    partitions: tuple[str, ...] = SOLIDITY_PARTITIONS
    metadata: Mapping[str, Any] = field(default_factory=dict)
    assignment_conflicts: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    duplicate_families: tuple[DuplicateFamily, ...] = ()
    schema_version: str = PARTITION_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PARTITION_MANIFEST_SCHEMA_VERSION:
            raise SolidityPartitionError(
                "unsupported Solidity partition manifest schema"
            )
        if not isinstance(self.examples, tuple):
            raise SolidityPartitionError(
                "partition examples must be an immutable tuple"
            )
        normalized_examples: list[SolidityPartitionExample] = []
        for item in self.examples:
            if isinstance(item, SolidityPartitionExample):
                normalized_examples.append(item)
            elif isinstance(item, Mapping):
                normalized_examples.append(
                    SolidityPartitionExample.from_dict(item)
                )
            else:
                raise SolidityPartitionError(
                    "partition examples must contain SolidityPartitionExample "
                    "records or mappings"
                )
        examples = tuple(
            sorted(normalized_examples, key=lambda item: item.sample_id)
        )
        sample_ids = tuple(item.sample_id for item in examples)
        if len(sample_ids) != len(set(sample_ids)):
            raise SolidityPartitionError(
                "partition examples must have unique sample IDs"
            )
        if not isinstance(self.assignments, Mapping):
            raise SolidityPartitionError("assignments must be a mapping")
        assignments = {
            _text(sample_id): _text(partition)
            for sample_id, partition in self.assignments.items()
        }
        unknown = sorted(set(assignments.values()) - set(SOLIDITY_PARTITIONS))
        if unknown:
            raise SolidityPartitionError(
                f"unknown Solidity partitions: {unknown}"
            )
        missing = sorted(set(sample_ids) - set(assignments))
        extra = sorted(set(assignments) - set(sample_ids))
        if missing or extra:
            raise SolidityPartitionError(
                "assignments must exactly cover examples; "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )
        partitions = tuple(self.partitions)
        if partitions != SOLIDITY_PARTITIONS:
            raise SolidityPartitionError(
                "partitions must exactly match the Solidity vocabulary"
            )
        config_digest = _text(self.config_digest)
        if (
            not config_digest
            or len(config_digest) > _MAX_VALUE_CHARS
            or "\x00" in config_digest
        ):
            raise SolidityPartitionError(
                "config_digest must be bounded non-empty text"
            )
        if not isinstance(self.assignment_conflicts, Mapping):
            raise SolidityPartitionError(
                "assignment_conflicts must be a mapping"
            )
        conflicts = {
            _text(sample_id): tuple(
                sorted(set(_values(candidate_partitions)))
            )
            for sample_id, candidate_partitions in self.assignment_conflicts.items()
            if len(set(_values(candidate_partitions))) > 1
        }
        invalid_conflict_partitions = sorted(
            {
                partition
                for partitions_for_sample in conflicts.values()
                for partition in partitions_for_sample
                if partition not in SOLIDITY_PARTITIONS
            }
        )
        if invalid_conflict_partitions:
            raise SolidityPartitionError(
                "assignment conflicts contain unknown partitions: "
                + ", ".join(invalid_conflict_partitions)
            )
        if not isinstance(self.metadata, Mapping) or any(
            not isinstance(key, str) for key in self.metadata
        ):
            raise SolidityPartitionError(
                "partition metadata must be a string-keyed mapping"
            )
        metadata = dict(self.metadata)
        unknown_metadata = sorted(set(metadata) - _METADATA_KEYS)
        if unknown_metadata:
            raise SolidityPartitionError(
                "unknown partition metadata fields: "
                + ", ".join(unknown_metadata)
            )
        if "seed" in metadata and (
            not isinstance(metadata["seed"], str)
            or len(metadata["seed"]) > _MAX_VALUE_CHARS
            or "\x00" in metadata["seed"]
        ):
            raise SolidityPartitionError(
                "partition metadata seed must be bounded text"
            )
        if "near_duplicate_jaccard_threshold" in metadata:
            threshold = metadata["near_duplicate_jaccard_threshold"]
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not math.isfinite(float(threshold))
                or not 0.0 < float(threshold) <= 1.0
            ):
                raise SolidityPartitionError(
                    "partition metadata duplicate threshold must be in (0, 1]"
                )
        for key in (
            "source_dataset_id",
            "source_revision",
            "source_split",
            "policy_digest",
            "source_snapshot_cid",
            "upstream_split_policy",
        ):
            if key in metadata and (
                not isinstance(metadata[key], str)
                or len(metadata[key]) > _MAX_VALUE_CHARS
                or "\x00" in metadata[key]
            ):
                raise SolidityPartitionError(
                    f"partition metadata {key} must be bounded text"
                )
        if metadata.get("source_dataset_id") not in (
            None,
            "",
            SOLIDITY_CPT_DATASET_ID,
        ):
            raise SolidityPartitionError(
                "partition metadata source_dataset_id drifted from pin"
            )
        if metadata.get("source_revision") not in (
            None,
            "",
            SOLIDITY_CPT_REVISION,
        ):
            raise SolidityPartitionError(
                "partition metadata source_revision drifted from pin"
            )
        if metadata.get("source_split") not in (None, "", UPSTREAM_SOURCE_SPLIT):
            raise SolidityPartitionError(
                "partition metadata source_split drifted from pin"
            )
        if metadata.get("upstream_split_policy") not in (
            None,
            "",
            "never_random_row_split",
        ):
            raise SolidityPartitionError(
                "upstream_split_policy must remain never_random_row_split"
            )
        families: list[DuplicateFamily] = []
        for item in self.duplicate_families:
            if isinstance(item, DuplicateFamily):
                families.append(item)
            elif isinstance(item, Mapping):
                families.append(DuplicateFamily.from_dict(item))
            else:
                raise SolidityPartitionError(
                    "duplicate_families must contain DuplicateFamily records"
                )
        object.__setattr__(self, "examples", examples)
        object.__setattr__(
            self,
            "assignments",
            MappingProxyType(dict(sorted(assignments.items()))),
        )
        object.__setattr__(self, "config_digest", config_digest)
        object.__setattr__(self, "partitions", partitions)
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(sorted(metadata.items())))
        )
        object.__setattr__(
            self,
            "assignment_conflicts",
            MappingProxyType(dict(sorted(conflicts.items()))),
        )
        object.__setattr__(
            self,
            "duplicate_families",
            tuple(sorted(families, key=lambda item: (item.kind, item.family_id))),
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    @property
    def samples_by_partition(self) -> Mapping[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {item: [] for item in self.partitions}
        for sample_id, partition in self.assignments.items():
            result[partition].append(sample_id)
        return MappingProxyType(
            {
                partition: tuple(sorted(sample_ids))
                for partition, sample_ids in result.items()
            }
        )

    def partition_of(self, sample_id: str) -> str:
        try:
            return self.assignments[sample_id]
        except KeyError:
            raise SolidityPartitionError(
                f"sample {sample_id!r} is absent from the partition manifest"
            ) from None

    def guard_result(self) -> SolidityPartitionGuardResult:
        return validate_solidity_partitions(self)

    def require_valid(self) -> SolidityPartitionGuardResult:
        return require_leakage_safe_partitions(self)

    def authorize_retrieval(
        self,
        query_sample_id: str,
        candidate_sample_ids: Sequence[str],
        *,
        graph_snapshot_id: str = "",
        embedding_snapshot_id: str = "",
        source_snapshot_cid: str = "",
        require_same_source_family: bool = True,
    ) -> "SolidityRetrievalFence":
        return require_retrieval_partition_fence(
            self,
            query_sample_id,
            candidate_sample_ids,
            graph_snapshot_id=graph_snapshot_id,
            embedding_snapshot_id=embedding_snapshot_id,
            source_snapshot_cid=source_snapshot_cid,
            require_same_source_family=require_same_source_family,
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "assignment_conflicts": {
                sample_id: list(partitions)
                for sample_id, partitions in self.assignment_conflicts.items()
            },
            "assignments": dict(self.assignments),
            "config_digest": self.config_digest,
            "duplicate_families": [
                item.to_dict() for item in self.duplicate_families
            ],
            "examples": [item.to_dict() for item in self.examples],
            "metadata": dict(self.metadata),
            "partitions": list(self.partitions),
            "samples_by_partition": {
                partition: list(sample_ids)
                for partition, sample_ids in self.samples_by_partition.items()
            },
            "schema_version": self.schema_version,
        }
        if include_digest:
            result["manifest_digest"] = self.digest
            result["partition_guard"] = self.guard_result().to_dict()
        return result

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityPartitionManifest":
        allowed = {
            "assignment_conflicts",
            "assignments",
            "config_digest",
            "duplicate_families",
            "examples",
            "manifest_digest",
            "metadata",
            "partition_guard",
            "partitions",
            "samples_by_partition",
            "schema_version",
        }
        if not isinstance(value, Mapping):
            raise SolidityPartitionError("partition manifest must be a mapping")
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SolidityPartitionError(
                "unknown partition manifest fields: " + ", ".join(unknown)
            )
        examples = tuple(
            SolidityPartitionExample.from_dict(item)
            for item in value.get("examples", ())
            if isinstance(item, Mapping)
        )
        assignments = value.get("assignments")
        conflicts: dict[str, tuple[str, ...]] = {}
        if not isinstance(assignments, Mapping):
            assignments = {}
            grouped = value.get("samples_by_partition", {})
            seen: dict[str, list[str]] = defaultdict(list)
            if isinstance(grouped, Mapping):
                for partition, sample_ids in grouped.items():
                    for sample_id in _values(sample_ids):
                        seen[sample_id].append(_text(partition))
                        assignments[sample_id] = _text(partition)
            conflicts = {
                sample_id: tuple(partitions)
                for sample_id, partitions in seen.items()
                if len(set(partitions)) > 1
            }
        raw_conflicts = value.get("assignment_conflicts", {})
        if isinstance(raw_conflicts, Mapping):
            conflicts.update(
                {
                    _text(sample_id): _values(partitions)
                    for sample_id, partitions in raw_conflicts.items()
                }
            )
        families = tuple(
            DuplicateFamily.from_dict(item)
            for item in value.get("duplicate_families", ())
            if isinstance(item, Mapping)
        )
        return cls(
            examples=examples,
            assignments=assignments,
            config_digest=_text(value.get("config_digest")),
            partitions=tuple(value.get("partitions", SOLIDITY_PARTITIONS)),
            metadata=(
                value.get("metadata", {})
                if isinstance(value.get("metadata", {}), Mapping)
                else {}
            ),
            assignment_conflicts=conflicts,
            duplicate_families=families,
            schema_version=value.get(
                "schema_version", PARTITION_MANIFEST_SCHEMA_VERSION
            ),
        )


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            parent = self.find(parent)
            self.parent[value] = parent
        return parent

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


def _union_values(
    union_find: _UnionFind,
    examples: Sequence[SolidityPartitionExample],
    values: Any,
) -> None:
    seen: dict[str, str] = {}
    for example in examples:
        for key in values(example):
            previous = seen.setdefault(key, example.sample_id)
            union_find.union(previous, example.sample_id)


def _bucket(*values: str) -> float:
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()
    return int(digest[:13], 16) / float(16**13)


def _choose_partition(
    group_id: str,
    examples: Sequence[SolidityPartitionExample],
    config: SolidityPartitionConfig,
) -> str:
    adversarial_ids = frozenset(config.adversarial_family_ids)
    held_addresses = frozenset(config.held_out_addresses)
    held_sources = frozenset(config.held_out_source_families)
    held_domains = frozenset(config.held_out_domains)

    if any(item.adversarial for item in examples) or any(
        adversarial_ids.intersection(item.duplicate_family_ids)
        or adversarial_ids.intersection(item.generated_code_family_ids)
        or adversarial_ids.intersection(item.fork_lineage_ids)
        for item in examples
    ):
        return ADVERSARIAL_PARTITION

    if any(
        item.held_out
        or item.domain in held_domains
        or held_sources.intersection(
            {value.casefold() for value in item.source_family_ids}
        )
        or held_addresses.intersection(item.addresses)
        for item in examples
    ):
        return HELD_OUT_PARTITION

    ratios = (
        (TRAIN_PARTITION, float(config.train_ratio)),
        (VALIDATION_PARTITION, float(config.validation_ratio)),
        (TEST_PARTITION, float(config.test_ratio)),
    )
    total = sum(weight for _, weight in ratios)
    value = _bucket(config.seed, "primary", group_id) * total
    boundary = 0.0
    for partition, weight in ratios:
        boundary += weight
        if value < boundary:
            return partition
    return ratios[-1][0]  # pragma: no cover - floating-point guard


def _build_duplicate_families(
    examples: Sequence[SolidityPartitionExample],
    union_find: _UnionFind,
) -> tuple[DuplicateFamily, ...]:
    groups: dict[str, list[str]] = defaultdict(list)
    for example in examples:
        groups[union_find.find(example.sample_id)].append(example.sample_id)
    families: list[DuplicateFamily] = []
    for group_id, sample_ids in sorted(groups.items()):
        if len(sample_ids) < 2:
            continue
        families.append(
            DuplicateFamily(
                family_id=group_id,
                kind="connected_component",
                sample_ids=tuple(sample_ids),
            )
        )
    return tuple(families)


def build_solidity_partitions(
    samples: Sequence[Any],
    config: SolidityPartitionConfig | None = None,
) -> SolidityPartitionManifest:
    """Group lineage-linked rows before deterministic partition assignment.

    Connected components are the unit of assignment.  The upstream single
    ``train`` split is never randomly divided row-by-row.
    """

    resolved = config or SolidityPartitionConfig()
    examples = tuple(
        sorted(
            (
                item
                if isinstance(item, SolidityPartitionExample)
                else SolidityPartitionExample.from_sample(item)
                for item in samples
            ),
            key=lambda item: item.sample_id,
        )
    )
    sample_ids = tuple(item.sample_id for item in examples)
    if len(sample_ids) != len(set(sample_ids)):
        raise SolidityPartitionError("partition input sample IDs must be unique")
    if not examples:
        raise SolidityPartitionError("partition input must contain at least one sample")

    union_find = _UnionFind(sample_ids)
    for values in (
        lambda item: item.content_digests,
        lambda item: item.lineage_repository_keys(),
        lambda item: item.lineage_source_family_keys(),
        lambda item: item.lineage_path_keys(),
        lambda item: item.addresses,
        lambda item: item.lineage_fork_keys(),
        lambda item: item.lineage_import_keys(),
        lambda item: item.generated_code_family_ids,
        lambda item: item.duplicate_family_ids,
    ):
        _union_values(union_find, examples, values)

    threshold = resolved.near_duplicate_jaccard_threshold
    for index, left in enumerate(examples):
        for right in examples[index + 1 :]:
            if (
                _jaccard(
                    left.near_duplicate_signature,
                    right.near_duplicate_signature,
                )
                >= threshold
            ):
                union_find.union(left.sample_id, right.sample_id)

    groups: dict[str, list[SolidityPartitionExample]] = defaultdict(list)
    for example in examples:
        groups[union_find.find(example.sample_id)].append(example)

    assignments: dict[str, str] = {}
    for group_id, members in sorted(groups.items()):
        partition = _choose_partition(group_id, members, resolved)
        for member in members:
            assignments[member.sample_id] = partition

    families = _build_duplicate_families(examples, union_find)
    manifest = SolidityPartitionManifest(
        examples=examples,
        assignments=assignments,
        config_digest=resolved.digest,
        duplicate_families=families,
        metadata={
            "near_duplicate_jaccard_threshold": (
                resolved.near_duplicate_jaccard_threshold
            ),
            "policy_digest": resolved.policy_digest or resolved.digest,
            "seed": resolved.seed,
            "source_dataset_id": resolved.source_dataset_id,
            "source_revision": resolved.source_revision,
            "source_snapshot_cid": resolved.source_snapshot_cid,
            "source_split": resolved.source_split,
            "upstream_split_policy": "never_random_row_split",
        },
    )
    require_leakage_safe_partitions(manifest)
    return manifest


build_solidity_partition_manifest = build_solidity_partitions


def validate_solidity_partitions(
    manifest: SolidityPartitionManifest | Mapping[str, Any],
) -> SolidityPartitionGuardResult:
    """Audit all persisted grouping signals for cross-partition leakage."""

    resolved = (
        manifest
        if isinstance(manifest, SolidityPartitionManifest)
        else SolidityPartitionManifest.from_dict(manifest)
    )
    assignments = resolved.assignments
    violations: list[SolidityLeakageViolation] = []

    def add(kind: str, key: str, sample_ids: Iterable[str]) -> None:
        by_partition: dict[str, list[str]] = defaultdict(list)
        for sample_id in sorted(set(sample_ids)):
            partition = assignments.get(sample_id)
            if partition:
                by_partition[partition].append(sample_id)
        if len(by_partition) <= 1:
            return
        violations.append(
            SolidityLeakageViolation(
                kind=kind,
                key=key,
                partitions=tuple(sorted(by_partition)),
                sample_ids_by_partition={
                    partition: tuple(sorted(ids))
                    for partition, ids in sorted(by_partition.items())
                },
            )
        )

    for sample_id, partitions in resolved.assignment_conflicts.items():
        if len(set(partitions)) > 1:
            violations.append(
                SolidityLeakageViolation(
                    kind="assignment",
                    key=sample_id,
                    partitions=tuple(sorted(set(partitions))),
                    sample_ids_by_partition={
                        partition: (sample_id,)
                        for partition in sorted(set(partitions))
                    },
                )
            )

    indexes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for example in resolved.examples:
        for kind, values in (
            ("content", example.content_digests),
            ("repository", example.lineage_repository_keys()),
            ("source_family", example.lineage_source_family_keys()),
            ("normalized_path", example.lineage_path_keys()),
            ("address", example.addresses),
            ("fork_lineage", example.lineage_fork_keys()),
            ("import_lineage", example.lineage_import_keys()),
            ("generated_code_family", example.generated_code_family_ids),
            ("duplicate_family", example.duplicate_family_ids),
        ):
            for key in values:
                indexes[(kind, key)].append(example.sample_id)
    for (kind, key), sample_ids in sorted(indexes.items()):
        add(kind, key, sample_ids)

    threshold = float(
        resolved.metadata.get("near_duplicate_jaccard_threshold", 0.80)
    )
    for index, left in enumerate(resolved.examples):
        for right in resolved.examples[index + 1 :]:
            similarity = _jaccard(
                left.near_duplicate_signature, right.near_duplicate_signature
            )
            if (
                similarity >= threshold
                and assignments[left.sample_id] != assignments[right.sample_id]
            ):
                add(
                    "near_duplicate",
                    _digest(
                        {
                            "left": left.sample_id,
                            "right": right.sample_id,
                            "threshold": threshold,
                        }
                    ),
                    (left.sample_id, right.sample_id),
                )

    for family in resolved.duplicate_families:
        add(family.kind, family.family_id, family.sample_ids)

    unique = {
        (item.kind, item.key, item.partitions): item for item in violations
    }
    ordered = tuple(
        sorted(unique.values(), key=lambda item: (item.kind, item.key))
    )
    return SolidityPartitionGuardResult(passed=not ordered, violations=ordered)


validate_solidity_partition_manifest = validate_solidity_partitions


def require_leakage_safe_partitions(
    manifest: SolidityPartitionManifest | Mapping[str, Any],
) -> SolidityPartitionGuardResult:
    result = validate_solidity_partitions(manifest)
    if not result.passed:
        raise SolidityPartitionLeakageError(
            "Solidity partition manifest crosses a lineage partition boundary",
            result,
        )
    return result


@dataclass(frozen=True, slots=True)
class SolidityRetrievalFenceViolation:
    candidate_sample_id: str
    reason: str
    candidate_partition: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "candidate_partition": self.candidate_partition,
            "candidate_sample_id": self.candidate_sample_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SolidityRetrievalFenceResult:
    passed: bool
    query_sample_id: str
    query_partition: str
    violations: tuple[SolidityRetrievalFenceViolation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "query_partition": self.query_partition,
            "query_sample_id": self.query_sample_id,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True, slots=True)
class SolidityRetrievalFence:
    """Receipt proving evaluation retrieval stayed inside one partition fence."""

    manifest_digest: str
    query_sample_id: str
    partition: str
    candidate_sample_ids: tuple[str, ...]
    graph_snapshot_id: str = ""
    embedding_snapshot_id: str = ""
    source_snapshot_cid: str = ""
    source_family_ids: tuple[str, ...] = ()
    schema_version: str = RETRIEVAL_FENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.partition not in SOLIDITY_PARTITIONS:
            raise SolidityPartitionError(
                "retrieval fence has an unknown partition"
            )
        if self.schema_version != RETRIEVAL_FENCE_SCHEMA_VERSION:
            raise SolidityPartitionError("unsupported retrieval fence schema")
        object.__setattr__(
            self,
            "candidate_sample_ids",
            tuple(sorted(set(self.candidate_sample_ids))),
        )
        object.__setattr__(
            self,
            "source_family_ids",
            _values(self.source_family_ids),
        )
        for field_name in (
            "manifest_digest",
            "query_sample_id",
            "graph_snapshot_id",
            "embedding_snapshot_id",
            "source_snapshot_cid",
        ):
            value = _text(getattr(self, field_name))
            if field_name in {"manifest_digest", "query_sample_id"} and not value:
                raise SolidityPartitionError(
                    f"{field_name} must be non-empty for a retrieval fence"
                )
            if len(value) > _MAX_VALUE_CHARS or "\x00" in value:
                raise SolidityPartitionError(
                    f"{field_name} must be bounded text"
                )
            object.__setattr__(self, field_name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_sample_ids": list(self.candidate_sample_ids),
            "embedding_snapshot_id": self.embedding_snapshot_id,
            "graph_snapshot_id": self.graph_snapshot_id,
            "manifest_digest": self.manifest_digest,
            "partition": self.partition,
            "query_sample_id": self.query_sample_id,
            "schema_version": self.schema_version,
            "source_family_ids": list(self.source_family_ids),
            "source_snapshot_cid": self.source_snapshot_cid,
        }


def validate_retrieval_partition_fence(
    manifest: SolidityPartitionManifest | Mapping[str, Any],
    query_sample_id: str,
    candidate_sample_ids: Sequence[str],
    *,
    graph_snapshot_id: str = "",
    embedding_snapshot_id: str = "",
    source_snapshot_cid: str = "",
    require_same_source_family: bool = True,
) -> SolidityRetrievalFenceResult:
    """Check candidates against partition, snapshot, and family fences."""

    resolved = (
        manifest
        if isinstance(manifest, SolidityPartitionManifest)
        else SolidityPartitionManifest.from_dict(manifest)
    )
    query_id = _text(query_sample_id)
    query_partition = resolved.assignments.get(query_id, "")
    examples = {item.sample_id: item for item in resolved.examples}
    violations: list[SolidityRetrievalFenceViolation] = []
    manifest_guard = validate_solidity_partitions(resolved)
    if not manifest_guard.passed:
        violations.append(
            SolidityRetrievalFenceViolation(
                candidate_sample_id="",
                reason="partition_manifest_has_leakage",
            )
        )
    query = examples.get(query_id)
    if query is None or not query_partition:
        violations.append(
            SolidityRetrievalFenceViolation(
                candidate_sample_id=query_id,
                reason="query_not_in_manifest",
            )
        )
    expected_graph = _text(graph_snapshot_id) or (
        query.graph_snapshot_id if query else ""
    )
    expected_embedding = _text(embedding_snapshot_id) or (
        query.embedding_snapshot_id if query else ""
    )
    expected_source = _text(source_snapshot_cid) or (
        query.source_snapshot_cid if query else ""
    )
    if (
        query is not None
        and graph_snapshot_id
        and query.graph_snapshot_id != _text(graph_snapshot_id)
    ):
        violations.append(
            SolidityRetrievalFenceViolation(
                candidate_sample_id=query_id,
                candidate_partition=query_partition,
                reason="query_graph_snapshot_mismatch",
            )
        )
    if (
        query is not None
        and embedding_snapshot_id
        and query.embedding_snapshot_id != _text(embedding_snapshot_id)
    ):
        violations.append(
            SolidityRetrievalFenceViolation(
                candidate_sample_id=query_id,
                candidate_partition=query_partition,
                reason="query_embedding_snapshot_mismatch",
            )
        )
    if (
        query is not None
        and source_snapshot_cid
        and query.source_snapshot_cid != _text(source_snapshot_cid)
    ):
        violations.append(
            SolidityRetrievalFenceViolation(
                candidate_sample_id=query_id,
                candidate_partition=query_partition,
                reason="query_source_snapshot_mismatch",
            )
        )
    query_families = (
        frozenset(query.source_family_ids) if query is not None else frozenset()
    )
    for candidate_id in tuple(dict.fromkeys(_values(candidate_sample_ids))):
        candidate = examples.get(candidate_id)
        candidate_partition = resolved.assignments.get(candidate_id, "")
        if candidate is None or not candidate_partition:
            violations.append(
                SolidityRetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    reason="candidate_not_in_manifest",
                )
            )
            continue
        if candidate_partition != query_partition:
            violations.append(
                SolidityRetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="cross_partition",
                )
            )
        if expected_graph and candidate.graph_snapshot_id != expected_graph:
            violations.append(
                SolidityRetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="graph_snapshot_mismatch",
                )
            )
        if (
            expected_embedding
            and candidate.embedding_snapshot_id != expected_embedding
        ):
            violations.append(
                SolidityRetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="embedding_snapshot_mismatch",
                )
            )
        if expected_source and candidate.source_snapshot_cid != expected_source:
            violations.append(
                SolidityRetrievalFenceViolation(
                    candidate_sample_id=candidate_id,
                    candidate_partition=candidate_partition,
                    reason="source_snapshot_mismatch",
                )
            )
        if require_same_source_family and query_families:
            candidate_families = frozenset(candidate.source_family_ids)
            if candidate_families and query_families.isdisjoint(
                candidate_families
            ):
                # Family fence is advisory only when both sides declare families
                # and share none; empty families fail open for pure content-only
                # rows inside the same partition/snapshot.
                violations.append(
                    SolidityRetrievalFenceViolation(
                        candidate_sample_id=candidate_id,
                        candidate_partition=candidate_partition,
                        reason="cross_source_family",
                    )
                )
    ordered = tuple(
        sorted(
            violations,
            key=lambda item: (
                item.candidate_sample_id,
                item.reason,
                item.candidate_partition,
            ),
        )
    )
    return SolidityRetrievalFenceResult(
        passed=not ordered,
        query_sample_id=query_id,
        query_partition=query_partition,
        violations=ordered,
    )


def require_retrieval_partition_fence(
    manifest: SolidityPartitionManifest | Mapping[str, Any],
    query_sample_id: str,
    candidate_sample_ids: Sequence[str],
    *,
    graph_snapshot_id: str = "",
    embedding_snapshot_id: str = "",
    source_snapshot_cid: str = "",
    require_same_source_family: bool = True,
) -> SolidityRetrievalFence:
    result = validate_retrieval_partition_fence(
        manifest,
        query_sample_id,
        candidate_sample_ids,
        graph_snapshot_id=graph_snapshot_id,
        embedding_snapshot_id=embedding_snapshot_id,
        source_snapshot_cid=source_snapshot_cid,
        require_same_source_family=require_same_source_family,
    )
    if not result.passed:
        raise SolidityRetrievalFenceError(
            "Solidity retrieval crossed a partition, snapshot, or family fence",
            result,
        )
    resolved = (
        manifest
        if isinstance(manifest, SolidityPartitionManifest)
        else SolidityPartitionManifest.from_dict(manifest)
    )
    query = {
        item.sample_id: item for item in resolved.examples
    }[result.query_sample_id]
    return SolidityRetrievalFence(
        manifest_digest=resolved.digest,
        query_sample_id=result.query_sample_id,
        partition=result.query_partition,
        candidate_sample_ids=_values(candidate_sample_ids),
        graph_snapshot_id=_text(graph_snapshot_id) or query.graph_snapshot_id,
        embedding_snapshot_id=(
            _text(embedding_snapshot_id) or query.embedding_snapshot_id
        ),
        source_snapshot_cid=(
            _text(source_snapshot_cid) or query.source_snapshot_cid
        ),
        source_family_ids=query.source_family_ids,
    )


enforce_retrieval_partition_fence = require_retrieval_partition_fence


__all__ = [
    "ADVERSARIAL_PARTITION",
    "DUPLICATE_FAMILY_SCHEMA_VERSION",
    "HELD_OUT_PARTITION",
    "PARTITION_CONFIG_SCHEMA_VERSION",
    "PARTITION_EXAMPLE_SCHEMA_VERSION",
    "PARTITION_MANIFEST_SCHEMA_VERSION",
    "RETRIEVAL_FENCE_SCHEMA_VERSION",
    "SOLIDITY_PARTITIONS",
    "TEST_PARTITION",
    "TRAIN_PARTITION",
    "UPSTREAM_SOURCE_SPLIT",
    "VALIDATION_PARTITION",
    "DuplicateFamily",
    "SolidityLeakageViolation",
    "SolidityPartitionConfig",
    "SolidityPartitionError",
    "SolidityPartitionExample",
    "SolidityPartitionGuardResult",
    "SolidityPartitionLeakageError",
    "SolidityPartitionManifest",
    "SolidityRetrievalFence",
    "SolidityRetrievalFenceError",
    "SolidityRetrievalFenceResult",
    "SolidityRetrievalFenceViolation",
    "build_solidity_partition_manifest",
    "build_solidity_partitions",
    "enforce_retrieval_partition_fence",
    "require_leakage_safe_partitions",
    "require_retrieval_partition_fence",
    "validate_retrieval_partition_fence",
    "validate_solidity_partition_manifest",
    "validate_solidity_partitions",
]
