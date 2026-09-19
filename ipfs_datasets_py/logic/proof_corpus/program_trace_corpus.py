"""SAWM-023 admitted execution-trace corpus.

Datasets owns corpus admission and split semantics. Rows are rights/privacy
admitted and exact-tree bound. Related families cannot leak across the six
disjoint partitions. Model nominations are never labels. An empty corpus
returns training_unavailable without blocking contracts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_accelerate_py.mcp_server.mcplusplus.kubo_cid import cid_for_bytes


PARTITIONS: Final[tuple[str, ...]] = (
    "training",
    "development",
    "held_out",
    "adversarial",
    "cross_repository",
    "ood",
)
EXCLUDED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "secret",
        "hidden_test",
        "private_reasoning",
        "unadmitted_source",
        "model_nomination",
        "model_label",
    }
)
ROW_REQUIRED: Final[tuple[str, ...]] = (
    "row_id",
    "partition",
    "repository_id",
    "commit_cid",
    "task_cid",
    "function_id",
    "family_id",
    "rights_admitted",
    "privacy_admitted",
    "tree_cid",
)


class ProgramTraceCorpusError(ValueError):
    """Closed corpus-admission failure."""


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return cid_for_bytes(encoded)


@dataclass(frozen=True, slots=True)
class ProgramTraceAdmission:
    row_id: str
    partition: str
    family_id: str
    tree_cid: str
    admitted: bool


@dataclass(frozen=True, slots=True)
class ProgramTraceSplitManifest:
    partition: str
    row_ids: tuple[str, ...]
    family_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgramTraceLeakageAudit:
    leaked_families: tuple[str, ...]
    clean: bool


@dataclass(frozen=True, slots=True)
class ProgramTraceCorpusManifest:
    splits: tuple[ProgramTraceSplitManifest, ...]
    training_unavailable: bool
    row_count: int
    manifest_cid: str


def admit_program_trace_row(row: Mapping[str, Any]) -> ProgramTraceAdmission:
    if not isinstance(row, Mapping):
        raise ProgramTraceCorpusError("row must be an object")
    forbidden = set(row) & EXCLUDED_FIELDS
    if forbidden:
        raise ProgramTraceCorpusError(
            f"excluded fields {sorted(forbidden)} cannot be admitted"
        )
    missing = [name for name in ROW_REQUIRED if name not in row]
    if missing:
        raise ProgramTraceCorpusError(f"row missing {missing}")
    partition = str(row["partition"])
    if partition not in PARTITIONS:
        raise ProgramTraceCorpusError(f"unknown partition {partition}")
    if row.get("rights_admitted") is not True or row.get("privacy_admitted") is not True:
        raise ProgramTraceCorpusError("row is not rights/privacy admitted")
    if not str(row.get("tree_cid") or "").strip():
        raise ProgramTraceCorpusError("row is not exact-tree bound")
    if row.get("label") in {"model_nomination", "provider_guess"}:
        raise ProgramTraceCorpusError("model nominations are never labels")
    return ProgramTraceAdmission(
        row_id=str(row["row_id"]),
        partition=partition,
        family_id=str(row["family_id"]),
        tree_cid=str(row["tree_cid"]),
        admitted=True,
    )


def audit_program_trace_leakage(
    rows: Sequence[Mapping[str, Any]],
) -> ProgramTraceLeakageAudit:
    families: dict[str, set[str]] = {}
    for row in rows:
        admitted = admit_program_trace_row(row)
        families.setdefault(admitted.family_id, set()).add(admitted.partition)
    leaked = tuple(
        sorted(family for family, parts in families.items() if len(parts) > 1)
    )
    return ProgramTraceLeakageAudit(leaked_families=leaked, clean=not leaked)


def build_program_trace_corpus(
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    fixture_path: str | Path | None = None,
) -> ProgramTraceCorpusManifest:
    material: list[Mapping[str, Any]] = list(rows or ())
    if fixture_path is not None:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        material.extend(payload.get("rows") or [])
    if not material:
        return ProgramTraceCorpusManifest(
            splits=tuple(
                ProgramTraceSplitManifest(partition=name, row_ids=(), family_ids=())
                for name in PARTITIONS
            ),
            training_unavailable=True,
            row_count=0,
            manifest_cid=_digest({"schema": "empty-trace-corpus", "rows": []}),
        )
    admitted = [admit_program_trace_row(row) for row in material]
    leakage = audit_program_trace_leakage(material)
    if not leakage.clean:
        raise ProgramTraceCorpusError(
            f"family leakage across partitions: {list(leakage.leaked_families)}"
        )
    splits = []
    for name in PARTITIONS:
        members = [item for item in admitted if item.partition == name]
        splits.append(
            ProgramTraceSplitManifest(
                partition=name,
                row_ids=tuple(item.row_id for item in members),
                family_ids=tuple(sorted({item.family_id for item in members})),
            )
        )
    training = next(item for item in splits if item.partition == "training")
    return ProgramTraceCorpusManifest(
        splits=tuple(splits),
        training_unavailable=len(training.row_ids) == 0,
        row_count=len(admitted),
        manifest_cid=_digest(
            {
                "schema": "program-trace-corpus",
                "splits": [
                    {
                        "partition": item.partition,
                        "row_ids": list(item.row_ids),
                        "family_ids": list(item.family_ids),
                    }
                    for item in splits
                ],
            }
        ),
    )
