"""Separate retrieval corpora and provenance (EAAEF-061)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final


CORPORA_SCHEMA: Final[str] = "ipfs_datasets_py/retrieval/agent-work-corpora@1"
CORPORA: Final[frozenset[str]] = frozenset(
    {
        "repository_truth",
        "imported_claims",
        "verified_receipts",
        "requirements",
        "external_docs",
        "legal_policy",
        "model_hypotheses",
    }
)


class CorpusError(ValueError):
    """Corpus mix or unknown domain."""


@dataclass(frozen=True)
class CorpusRecord:
    corpus: str
    item_id: str
    trust_filtered: bool = True

    def __post_init__(self) -> None:
        if self.corpus not in CORPORA:
            raise CorpusError(f"unknown corpus: {self.corpus}")
        if not str(self.item_id).strip():
            raise CorpusError("item_id is required")
        if self.corpus == "imported_claims" and not self.trust_filtered:
            raise CorpusError("imported claims must be trust-filtered")

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": CORPORA_SCHEMA,
                "corpus": self.corpus,
                "item_id": self.item_id,
                "trust_filtered": bool(self.trust_filtered),
            }
        )


def separate(*records: CorpusRecord) -> Mapping[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {name: [] for name in sorted(CORPORA)}
    for record in records:
        grouped[record.corpus].append(record.item_id)
    return MappingProxyType({key: tuple(value) for key, value in grouped.items()})
