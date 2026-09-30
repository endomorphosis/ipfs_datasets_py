"""Local campaign that turns a pinned SkillCenter corpus into Intent IR features.

The optimizer never opens the Hub. Callers pin ``Publicus/skillcenter-ir``
first, then census, normalize, split, compile, and train from that directory.
Learned state is a structural feature candidate. It does not admit formulas,
authorize tools, or execute skill text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..evaluation.splits import (
    HELD_OUT_DOMAIN_PARTITION,
    HELD_OUT_TIME_REVISION_PARTITION,
    TEST_PARTITION,
    TRAIN_PARTITION,
    VALIDATION_PARTITION,
    IntentSplitConfig,
    IntentSplitExample,
    IntentSplitManifest,
    build_intent_splits,
)
from ..normalize.skill import (
    INTENT_NORMALIZER_VERSION,
    SkillCenterIntentNormalizer,
    SkillNormalizationPolicyError,
)
from ..source_adapters.policy import (
    SKILL_SOURCE_POLICY_VERSION,
    AllowedUseDecision,
    SkillSourcePolicy,
)
from ..source_adapters.skillcenter import SkillCenterSkillRecord


DATASET_REPO_ID = "Publicus/skillcenter-ir"
DATASET_REVISION = "2cc11a73403d03c0679ffa909c893ef6a850048a"
UPSTREAM_DATASET_ID = "Tommysha/skillcenter-bundles"
UPSTREAM_REVISION = "f9dd4fec3c86d85ebf116c7408ac5ce602c418a1"
PIN_SCHEMA = "skillcenter-intent-training-pin/v1"
CENSUS_SCHEMA = "skillcenter-intent-training-census/v1"
CAPSULE_SCHEMA = "skillcenter-intent-training-capsule/v1"
TARGET_SCHEMA = "skillcenter-intent-training-targets/v1"
TRAIN_SCHEMA = "skillcenter-intent-training-run/v1"
EVAL_SCHEMA = "intent-formalization-benchmark/v1"
ELIGIBLE_COVERAGE_SCHEMA = "skillcenter-intent-eligible-coverage/v1"
FULL_READY_VOCABULARY_SCHEMA = "skillcenter-intent-full-ready-vocabulary/v1"
STRUCTURAL_VIEW_V2_SCHEMA = "skillcenter-structural-atom-view/v2"
STREAMED_TRAIN_SCHEMA = "skillcenter-intent-streamed-training/v2"
STREAMED_SPACE_RECORD_SCHEMA = "skillcenter-intent-streamed-feature-space/v1"
V2_MAX_SECONDS = 3600.0
_DESCRIPTOR_KEYS = (
    "logic_family",
    "profile",
    "properties",
    "view_role",
    "representation_kind",
    "producer_id",
)
_HOLDOUT_PARTITIONS = (
    TEST_PARTITION,
    HELD_OUT_DOMAIN_PARTITION,
    HELD_OUT_TIME_REVISION_PARTITION,
)
_V2_UNTOUCHED = (
    "pin_receipt.json",
    "training_result.json",
    "training_receipt.json",
    "eval_receipt.json",
    "reservoir_coverage.json",
    "reservoir_feature_state.json",
    "eligible_coverage.json",
    "full_ready_vocabulary.json",
    "corpus_split.json",
    "corpus_vocabulary_census.json",
    "vocabulary_census.json",
    "target_index.parquet",
    "pilot_target_index.parquet",
    "pilot_split.json",
    "candidate_staging/candidate.json",
)
PILOT_SEED = "intent-ir-skillcenter-pilot-v1"
PILOT_SOURCE_LIMIT = 1024
PAIRWISE_SPLIT_LIMIT = 4096
_INDEX_CHECKPOINT_EVERY = 2048
DISK_RESERVE_BYTES = 20 * 1024 * 1024 * 1024
TRAIN_LATENT_WIDTH = 16
TRAIN_EPOCHS = 8
TRAIN_LEARNING_RATE = 0.02
TRAIN_MAX_SECONDS = 240.0
TRAIN_SEED = 1729
STRUCTURAL_VIEW_SCHEMA = "skillcenter-structural-atom-view/v1"
_MIN_VERB_DOCUMENTS = 2
_OPEN_VERB = "<open-verb>"
_TEXT_ATOM = "<text>"
_IDENTIFIER_RE = re.compile(
    r"^(?P<scheme>intent:[a-z0-9_-]+|skillcenter-span):[0-9a-f]{16,}$"
)
_MUTABLE_REVISIONS = frozenset(
    {"", "head", "latest", "main", "master", "refs/heads/main", "refs/heads/master"}
)
_AUTHORITY = ("qualified", "admitted", "formalized")
_SNAPSHOT_ALLOW_PATTERNS = (
    "manifest.json",
    "README.md",
    "indexes/corpus_chunks.parquet",
    "data/corpus/*.parquet",
)
_CORPUS_FIELDS = (
    "bundle_sha256",
    "dataset_id",
    "dataset_revision",
    "domain",
    "language",
    "library_md",
    "metadata_yaml",
    "overall_score",
    "primary_source_id",
    "profile",
    "repository_file",
    "skill_id",
    "skill_kind",
    "skill_md",
    "source_id",
    "source_type",
    "source_url",
    "title",
)
_KEEP_USES = frozenset(
    {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH.value,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION.value,
    }
)


class SkillCenterTrainingError(ValueError):
    """The campaign refused a pin, a row, or a trainer contract."""


def cache_root(revision: str = DATASET_REVISION) -> Path:
    """Return the local campaign directory for one immutable Hub revision."""

    configured = str(os.environ.get("XDG_DATA_HOME") or "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / ".local" / "share"
    return base / "ipfs_datasets_py" / "intent-ir" / "skillcenter-training" / revision


def refuse_mutable_revision(revision: str) -> str:
    """Return a stripped revision, or refuse a branch name."""

    text = str(revision or "").strip()
    if text.casefold() in _MUTABLE_REVISIONS:
        raise SkillCenterTrainingError("dataset revision must be an immutable commit")
    return text


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(value).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def enable_offline_environment() -> None:
    """Stop the optimizer process from opening the Hub or a model host."""

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def record_from_corpus_row(row: Mapping[str, Any]) -> SkillCenterSkillRecord:
    """Rebuild the record type the policy and normalizer already accept."""

    score = row.get("overall_score")
    return SkillCenterSkillRecord(
        skill_id=str(row.get("skill_id") or ""),
        domain=str(row.get("domain") or ""),
        profile=str(row.get("profile") or ""),
        source_type=str(row.get("source_type") or ""),
        source_url=str(row.get("source_url") or ""),
        title=str(row.get("title") or ""),
        overall_score=None if score is None else float(score),
        skill_kind=str(row.get("skill_kind") or ""),
        language=str(row.get("language") or ""),
        source_id=str(row.get("source_id") or ""),
        primary_source_id=str(row.get("primary_source_id") or ""),
        metadata_yaml=str(row.get("metadata_yaml") or ""),
        skill_md=str(row.get("skill_md") or ""),
        library_md=str(row.get("library_md") or ""),
        dataset_id=str(row.get("dataset_id") or ""),
        dataset_revision=str(row.get("dataset_revision") or ""),
        repository_file=str(row.get("repository_file") or ""),
        bundle_sha256=str(row.get("bundle_sha256") or ""),
    )


def iter_corpus_rows(snapshot: Path):
    """Stream corpus shards. BM25 postings and vectors are not opened."""

    import pyarrow.parquet as pq

    directory = Path(snapshot) / "data" / "corpus"
    paths = sorted(directory.glob("*.parquet"))
    if not paths:
        raise SkillCenterTrainingError(f"no corpus shards under {directory}")
    columns = list(_CORPUS_FIELDS) + ["entry_cid", "content_sha256"]
    for path in paths:
        table = pq.ParquetFile(path).read()
        present = [name for name in columns if name in table.column_names]
        for row in table.select(present).to_pylist():
            yield row


def pin_training_snapshot(
    output_dir: Path,
    *,
    revision: str = DATASET_REVISION,
    measure_bytes: Callable[[], int],
    download: Callable[[Path], Path],
    disk_free_bytes: Callable[[Path], int] | None = None,
) -> dict[str, Any]:
    """Download the corpus snapshot only when the disk check passes."""

    pinned = refuse_mutable_revision(revision)
    if pinned != DATASET_REVISION:
        raise SkillCenterTrainingError("campaign pin revision does not match Publicus/skillcenter-ir")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_bytes = int(measure_bytes())
    if snapshot_bytes < 1:
        raise SkillCenterTrainingError("measured snapshot size must be positive")
    free = (disk_free_bytes or _disk_free)(output_dir)
    if free < snapshot_bytes + DISK_RESERVE_BYTES:
        raise SkillCenterTrainingError(
            "free space is below the snapshot size plus the 20GB capsule reserve"
        )
    snapshot = Path(download(output_dir))
    manifest_path = snapshot / "manifest.json"
    if not manifest_path.is_file():
        raise SkillCenterTrainingError("pinned snapshot is missing manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_repo_id") != DATASET_REPO_ID:
        raise SkillCenterTrainingError("manifest dataset_repo_id is not Publicus/skillcenter-ir")
    if manifest.get("dataset_id") != UPSTREAM_DATASET_ID:
        raise SkillCenterTrainingError("manifest dataset_id is not Tommysha/skillcenter-bundles")
    if manifest.get("dataset_revision") != UPSTREAM_REVISION:
        raise SkillCenterTrainingError("manifest upstream revision is not the pinned bundle commit")
    files = sorted(
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    receipt = {
        "schema": PIN_SCHEMA,
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": pinned,
        "upstream_dataset_id": UPSTREAM_DATASET_ID,
        "upstream_revision": str(manifest["dataset_revision"]),
        "manifest_sha256": sha256_file(manifest_path),
        "snapshot_bytes": snapshot_bytes,
        "file_count": len(files),
        "files": files,
        "allow_patterns": list(_SNAPSHOT_ALLOW_PATTERNS),
    }
    write_json(output_dir / "pin_receipt.json", receipt)
    return receipt


def census_policy(snapshot: Path, output_dir: Path) -> dict[str, Any]:
    """Classify every corpus row. The body is not copied into the census."""

    policy = SkillSourcePolicy()
    rows: list[dict[str, Any]] = []
    use_counts: Counter[str] = Counter()
    license_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    repository_counts: Counter[str] = Counter()
    train_sources: set[str] = set()
    train_repositories: set[str] = set()
    for raw in iter_corpus_rows(snapshot):
        record = record_from_corpus_row(raw)
        decision = policy.evaluate(record)
        declared_cid = str(raw.get("entry_cid") or "")
        actual_cid = record.entry_cid
        if declared_cid and declared_cid != actual_cid:
            raise SkillCenterTrainingError(
                f"entry_cid drifted for skill {record.skill_id}"
            )
        declared_body = str(raw.get("content_sha256") or "")
        if declared_body and declared_body != record.content_sha256:
            raise SkillCenterTrainingError(
                f"content_sha256 drifted for skill {record.skill_id}"
            )
        allowed = decision.allowed_use.value
        use_counts[allowed] += 1
        license_counts[decision.license_decision.status.value] += 1
        domain_counts[record.domain] += 1
        repository_counts[record.repository_file] += 1
        if allowed == AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH.value:
            if record.primary_source_id:
                train_sources.add(record.primary_source_id)
            if record.repository_file:
                train_repositories.add(record.repository_file)
        rows.append(
            {
                "entry_cid": actual_cid,
                "skill_id": record.skill_id,
                "allowed_use": allowed,
                "license_status": decision.license_decision.status.value,
                "license_reason": decision.license_decision.reason_code,
                "trust": decision.trust_decision.value,
                "domain": record.domain,
                "profile": record.profile,
                "repository_file": record.repository_file,
                "source_type": record.source_type,
                "language": record.language,
                "primary_source_id": record.primary_source_id,
                "dataset_revision": record.dataset_revision,
                "content_sha256": record.content_sha256,
                "skill_md_bytes": len(record.skill_md.encode("utf-8")),
                "finding_codes": [item.code for item in decision.findings],
                "finding_categories": [item.category.value for item in decision.findings],
                "policy_version": decision.policy_version,
            }
        )
    _write_parquet(Path(output_dir) / "policy_census.parquet", rows)
    summary = {
        "schema": CENSUS_SCHEMA,
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "policy_version": SKILL_SOURCE_POLICY_VERSION,
        "row_count": len(rows),
        "allowed_use": dict(sorted(use_counts.items())),
        "license_status": dict(sorted(license_counts.items())),
        "domain": dict(sorted(domain_counts.items())),
        "repository_file": dict(sorted(repository_counts.items())),
        "train_primary_source_count": len(train_sources),
        "train_repository_count": len(train_repositories),
        "train_eligible": use_counts[AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH.value],
        "eval_only": use_counts[AllowedUseDecision.ALLOW_INTERNAL_EVALUATION.value],
    }
    write_json(Path(output_dir) / "policy_census.json", summary)
    return summary


def _require_checkpoint_every(checkpoint_every: int) -> int:
    if isinstance(checkpoint_every, bool) or not isinstance(checkpoint_every, int) or checkpoint_every < 1:
        raise SkillCenterTrainingError("checkpoint_every must be a positive integer")
    return checkpoint_every


def build_intent_capsule(
    snapshot: Path,
    campaign_dir: Path,
    *,
    checkpoint_every: int = _INDEX_CHECKPOINT_EVERY,
) -> dict[str, Any]:
    """Normalize policy-eligible bodies into content-addressed Intent IR.

    Every ``checkpoint_every`` new documents the index is replaced atomically.
    A later run skips entry cids already present in that index.
    """

    checkpoint_every = _require_checkpoint_every(checkpoint_every)
    campaign_dir = Path(campaign_dir)
    census_path = campaign_dir / "policy_census.parquet"
    if not census_path.is_file():
        raise SkillCenterTrainingError("policy census is required before the capsule")
    allowed = {
        str(row["entry_cid"]): str(row["allowed_use"])
        for row in _read_parquet(census_path)
        if str(row["allowed_use"]) in _KEEP_USES
    }
    documents = campaign_dir / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    index_path = campaign_dir / "capsule_index.parquet"
    carried = {
        str(row["entry_cid"]): dict(row) for row in _read_parquet(index_path)
    } if index_path.is_file() else {}
    normalizer = SkillCenterIntentNormalizer()
    kept: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    new_since_flush = 0

    def flush(*, final: bool) -> None:
        rows = list(kept)
        if not final:
            rows.extend(carried.values())
        rows.sort(key=lambda row: row["entry_cid"])
        _write_parquet(index_path, rows)
        if not final:
            _note_checkpoint("capsule_index", len(rows))

    for raw in iter_corpus_rows(snapshot):
        record = record_from_corpus_row(raw)
        entry_cid = record.entry_cid
        allowed_use = allowed.get(entry_cid)
        if allowed_use is None:
            dropped["policy"] += 1
            carried.pop(entry_cid, None)
            continue
        previous = carried.pop(entry_cid, None)
        if previous is not None:
            kept.append(previous)
            continue
        try:
            result = normalizer.normalize_with_diagnostics(record)
        except SkillNormalizationPolicyError:
            dropped["policy_recheck"] += 1
            continue
        document = result.document
        if not (document.statements or document.actions or document.control_edges):
            dropped["empty_semantics"] += 1
            continue
        from ..canonicalize import canonical_intent_ir_bytes

        raw_document = canonical_intent_ir_bytes(document)
        digest = hashlib.sha256(raw_document).hexdigest()
        target = documents / f"{digest}.json"
        if not target.exists():
            _write_bytes_atomic(target, raw_document)
        source = document.sources[0]
        kept.append(
            {
                "entry_cid": entry_cid,
                "document_id": document.document_id,
                "document_sha256": digest,
                "allowed_use": allowed_use,
                "domain": record.domain,
                "primary_source_id": record.primary_source_id,
                "repository_file": record.repository_file,
                "source_revision": source.source_revision,
                "content_sha256": record.content_sha256,
                "normalizer_version": result.normalizer_version or INTENT_NORMALIZER_VERSION,
                "diagnostic_codes": [item.code for item in result.diagnostics],
            }
        )
        new_since_flush += 1
        if new_since_flush >= checkpoint_every:
            flush(final=False)
            new_since_flush = 0
    flush(final=True)
    summary = {
        "schema": CAPSULE_SCHEMA,
        "document_count": len(kept),
        "dropped": dict(sorted(dropped.items())),
        "normalizer_version": INTENT_NORMALIZER_VERSION,
        "train_documents": sum(
            row["allowed_use"] == AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH.value for row in kept
        ),
        "eval_documents": sum(
            row["allowed_use"] == AllowedUseDecision.ALLOW_INTERNAL_EVALUATION.value
            for row in kept
        ),
    }
    write_json(campaign_dir / "capsule_summary.json", summary)
    return summary


def guard_full_corpus_split(row_count: int, *, full_corpus: bool) -> None:
    """Accept a full-corpus split that uses the shingle blocking index.

    A draw larger than ``PAIRWISE_SPLIT_LIMIT`` must set ``full_corpus``.
    Near-duplicate grouping is the prefix index inside ``build_intent_splits``.
    """

    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise SkillCenterTrainingError("row count must be a non-negative integer")
    if not isinstance(full_corpus, bool):
        raise SkillCenterTrainingError("full_corpus must be a boolean")
    if row_count > PAIRWISE_SPLIT_LIMIT and not full_corpus:
        raise SkillCenterTrainingError(
            f"refusing {row_count} rows without full_corpus; "
            "use the shingle blocking index for a full-corpus split"
        )


def _train_rows(campaign_dir: Path) -> list[dict[str, Any]]:
    rows = [
        row for row in _read_parquet(campaign_dir / "capsule_index.parquet")
        if row["allowed_use"] == AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH.value
    ]
    if not rows:
        raise SkillCenterTrainingError("capsule has no train-eligible documents")
    return rows


def _statement_shingles(document: Any) -> tuple[str, ...]:
    text = "\n".join(
        statement.normalized_text
        for statement in sorted(document.statements, key=lambda item: item.statement_id)
    )
    if not text:
        return ()
    return IntentSplitExample.from_sample(
        {"sample_id": document.document_id, "text": text}
    ).near_duplicate_signature


def _split_examples(rows: Sequence[Mapping[str, Any]], signatures: Mapping[str, tuple[str, ...]] | None = None):
    signatures = signatures or {}
    return tuple(
        IntentSplitExample(
            sample_id=str(row["document_id"]),
            domain=str(row["domain"] or ""),
            primary_source_ids=(str(row["primary_source_id"]),) if row.get("primary_source_id") else (),
            repository_ids=(str(row["repository_file"]),) if row.get("repository_file") else (),
            source_document_ids=(str(row["entry_cid"]),),
            source_revisions=(str(row["source_revision"]),) if row.get("source_revision") else (),
            content_digests=(str(row["content_sha256"]),),
            near_duplicate_signature=signatures.get(str(row["document_id"]), ()),
        )
        for row in rows
    )


def _holdout_config(rows: Sequence[Mapping[str, Any]], seed: str) -> tuple[tuple[str, ...], tuple[str, ...], IntentSplitConfig]:
    domains = Counter(str(row["domain"] or "") for row in rows)
    held_domains = _smallest_holdout(domains)
    revisions = sorted({str(row["source_revision"]) for row in rows if row.get("source_revision")})
    held_revisions = (revisions[-1],) if len(revisions) > 1 else ()
    config = IntentSplitConfig(
        seed=seed,
        held_out_domains=held_domains,
        held_out_revisions=held_revisions,
    )
    return held_domains, held_revisions, config


def build_pilot_split(campaign_dir: Path, *, seed: str = PILOT_SEED) -> dict[str, Any]:
    """Draw at most 1,024 train-eligible documents and split that draw only."""

    campaign_dir = Path(campaign_dir)
    sampled = _pilot_draw(_train_rows(campaign_dir), seed=seed, limit=PILOT_SOURCE_LIMIT)
    guard_full_corpus_split(len(sampled), full_corpus=False)
    held_domains, held_revisions, config = _holdout_config(sampled, seed)
    manifest = build_intent_splits(_split_examples(sampled), config)
    payload = manifest.to_dict()
    payload["schema"] = "skillcenter-intent-pilot-split/v1"
    payload["pilot_row_count"] = len(sampled)
    payload["held_out_domains"] = list(held_domains)
    payload["held_out_revisions"] = list(held_revisions)
    digest = write_json(campaign_dir / "pilot_split.json", payload)
    payload["file_sha256"] = digest
    return payload


def build_corpus_split(campaign_dir: Path, *, seed: str = PILOT_SEED) -> dict[str, Any]:
    """Split every train-eligible capsule row with the shingle blocking index."""

    campaign_dir = Path(campaign_dir)
    rows = _train_rows(campaign_dir)
    guard_full_corpus_split(len(rows), full_corpus=True)
    signatures = {
        str(row["document_id"]): _statement_shingles(_load_document(campaign_dir, str(row["document_sha256"])))
        for row in rows
    }
    held_domains, held_revisions, config = _holdout_config(rows, seed)
    manifest = build_intent_splits(_split_examples(rows, signatures), config)
    payload = manifest.to_dict()
    payload["schema"] = "skillcenter-intent-corpus-split/v1"
    payload["corpus_row_count"] = len(rows)
    payload["blocking_index"] = "jaccard-prefix-shingles/v1"
    payload["held_out_domains"] = list(held_domains)
    payload["held_out_revisions"] = list(held_revisions)
    digest = write_json(campaign_dir / "corpus_split.json", payload)
    payload["file_sha256"] = digest
    return payload


def feature_training_envelope(document: Any):
    """Keep structured projections when untyped statement text is opaque.

    ``prepare_intent_targets`` refuses a document when any statement lacks a
    typed predicate. SkillCenter's structural normalizer does not invent
    predicates, so that refusal would drop the whole corpus. Opaque formula
    ids stay in ``qualification_gaps``. A failed decompiler review stays a
    qualification observation and does not become a passing check. Schema,
    nonempty-semantics, and compiler failures still block the row.
    """

    from ...formalization.autoencoder.domain_targets import (
        build_target_envelope,
        prepare_intent_targets,
    )

    full = prepare_intent_targets(document)
    payload = full.to_dict()
    if payload["ready_for_training"]:
        return full
    blocking = [
        row for row in payload["validation"]
        if row.get("validator_id") != "intent_ir.decompiler_review" and row.get("status") != "passed"
    ]
    structured = [
        dict(row) for row in payload["projections"]
        if row.get("logic_family") and row.get("expression")
    ]
    if blocking or not structured:
        return full
    checks = []
    for row in payload["validation"]:
        item = dict(row)
        if item.get("validator_id") == "intent_ir.decompiler_review":
            item["stage"] = "qualification"
            item["required"] = False
        checks.append(item)
    return build_target_envelope(
        domain_id="intent_ir",
        source_digest=payload["source_digest"],
        projections=structured,
        validation=checks,
        unsupported=(),
        qualification_gaps=[*payload["qualification_gaps"], *payload["unsupported"]],
    )


def _census_name(split_name: str) -> str:
    if split_name == "pilot_split.json":
        return "vocabulary_census.json"
    if split_name == "corpus_split.json":
        return "corpus_vocabulary_census.json"
    raise SkillCenterTrainingError("split file must be the pilot or corpus split")


def build_targets(
    campaign_dir: Path,
    *,
    split_name: str = "pilot_split.json",
    checkpoint_every: int = _INDEX_CHECKPOINT_EVERY,
) -> dict[str, Any]:
    """Compile split documents and census the train-only feature vocabulary.

    Compiled envelopes are recorded in ``target_progress.parquet``. A resumed
    run reuses those rows. ``target_index.parquet`` is replaced only after
    every assignment in this split has been compiled.
    """

    from ..formalize.compiler import INTENT_FORMALIZATION_COMPILER_VERSION

    checkpoint_every = _require_checkpoint_every(checkpoint_every)
    campaign_dir = Path(campaign_dir)
    census_name = _census_name(split_name)
    manifest = json.loads((campaign_dir / split_name).read_text(encoding="utf-8"))
    assignments = {
        str(sample_id): str(partition)
        for sample_id, partition in dict(manifest["assignments"]).items()
    }
    by_document = {
        str(row["document_id"]): row
        for row in _read_parquet(campaign_dir / "capsule_index.parquet")
    }
    envelope_dir = campaign_dir / "envelopes"
    envelope_dir.mkdir(parents=True, exist_ok=True)
    progress_path = campaign_dir / "target_progress.parquet"
    pending = {
        str(row["document_id"]): dict(row)
        for row in (_read_parquet(progress_path) if progress_path.is_file() else [])
        if row.get("document_id")
    }
    index: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    new_since_flush = 0

    def flush_progress() -> None:
        rows = list(index)
        rows.extend(pending.values())
        _write_parquet(progress_path, rows)
        _note_checkpoint("target_progress", len(rows))

    for document_id, partition in sorted(assignments.items()):
        capsule_row = by_document[document_id]
        previous = pending.pop(document_id, None)
        reused = _reuse_target_progress(previous, capsule_row, partition, envelope_dir)
        if reused is not None:
            if not reused["ready"]:
                failures[str(reused["failure_detail"] or "not_ready")] += 1
            index.append(reused)
            continue
        document = _load_document(campaign_dir, str(capsule_row["document_sha256"]))
        try:
            envelope = feature_training_envelope(document)
        except (TypeError, ValueError) as exc:
            name = type(exc).__name__
            failures[name] += 1
            row = _target_index_row(capsule_row, partition, "", False, name)
            row["failure_detail"] = name
            index.append(row)
            new_since_flush += 1
            if new_since_flush >= checkpoint_every:
                flush_progress()
                new_since_flush = 0
            continue
        payload = envelope.to_dict()
        ready = bool(payload["ready_for_training"]) and not payload["unsupported"]
        detail = ""
        if not ready:
            detail = ",".join(
                str(item.get("validator_id") or item.get("reason") or "not_ready")
                for item in list(payload["validation"]) + list(payload["unsupported"])
                if isinstance(item, Mapping) and item.get("status") not in {None, "passed"}
            ) or "not_ready"
            failures[detail] += 1
        _write_bytes_atomic(envelope_dir / f"{envelope.digest}.json", envelope.canonical_bytes)
        row = _target_index_row(
            capsule_row,
            partition,
            envelope.digest,
            ready,
            "" if ready else "not_ready",
        )
        row["failure_detail"] = detail
        index.append(row)
        new_since_flush += 1
        if new_since_flush >= checkpoint_every:
            flush_progress()
            new_since_flush = 0
    _write_parquet(
        campaign_dir / "target_index.parquet",
        [_public_target_row(row) for row in index],
    )
    _write_parquet(progress_path, index)
    train_envelopes = _load_partition_envelopes(campaign_dir, index, TRAIN_PARTITION)
    census = _vocabulary_census(train_envelopes)
    census.update(
        {
            "schema": TARGET_SCHEMA,
            "compiler_version": INTENT_FORMALIZATION_COMPILER_VERSION,
            "target_count": len(index),
            "ready_count": sum(bool(row["ready"]) for row in index),
            "failures": dict(sorted(failures.items())),
        }
    )
    write_json(campaign_dir / census_name, census)
    return census


def _expression_field(path: Sequence[Any]) -> str:
    for part in reversed(path):
        if isinstance(part, str):
            return part
    return ""


def _structural_leaf(field: str, value: Any, kept_verbs: frozenset[str]) -> Any:
    if field == "object_refs" and isinstance(value, str):
        return _TEXT_ATOM
    if field == "verb" and isinstance(value, str):
        return value if value in kept_verbs else _OPEN_VERB
    if isinstance(value, str):
        match = _IDENTIFIER_RE.fullmatch(value)
        if match is not None:
            return match.group("scheme")
    return value


def _leaf_key(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _structural_atom_tree(expression: Any, *, kept_verbs: frozenset[str]) -> dict[str, Any]:
    """Collapse list positions, identifier leaves, and one-off verbs to presence atoms."""

    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import _tokens

    tree: dict[str, Any] = {}
    for token in _tokens(expression):
        path, value = json.loads(token)
        if not isinstance(path, list):
            continue
        field = _expression_field(path)
        node = tree
        for part in path:
            if not isinstance(part, str):
                continue
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[_leaf_key(_structural_leaf(field, value, kept_verbs))] = True
    if not tree:
        raise SkillCenterTrainingError("structural view dropped every atom")
    return tree


def _verb_leaves(envelope: Any) -> set[str]:
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import _tokens

    verbs: set[str] = set()
    for projection in envelope.to_dict()["projections"]:
        expression = projection.get("expression")
        if not expression:
            continue
        for token in _tokens(expression):
            path, value = json.loads(token)
            if (
                isinstance(path, list)
                and _expression_field(path) == "verb"
                and isinstance(value, str)
            ):
                verbs.add(value)
    return verbs


def _presence_token(parent: tuple[str, ...], leaf: str) -> str:
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import _raw

    return _raw(([*parent, leaf], True)).decode()


def _split_structural_atoms(expression: Any) -> tuple[dict[str, Any], dict[str, set[tuple[str, ...]]]]:
    """Separate verb leaves from the structural atoms that do not depend on them."""

    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import _tokens

    tree: dict[str, Any] = {}
    verbs: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for token in _tokens(expression):
        path, value = json.loads(token)
        if not isinstance(path, list):
            continue
        parent = tuple(part for part in path if isinstance(part, str))
        field = _expression_field(path)
        if field == "verb" and isinstance(value, str):
            verbs[value].add(parent)
            continue
        node = tree
        for part in parent:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[_leaf_key(_structural_leaf(field, value, frozenset()))] = True
    return tree, verbs


def _empty_structural_vocabulary(projection_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "closed_tokens": {name: set() for name in projection_ids},
        "verb_parents": {name: defaultdict(set) for name in projection_ids},
        "document_counts": Counter(),
    }


def _accumulate_structural_vocabulary(vocabulary: dict[str, Any], envelope: Any, projection_ids: Sequence[str]) -> None:
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import _tokens

    selected = set(projection_ids)
    document_verbs: set[str] = set()
    for projection in envelope.to_dict()["projections"]:
        name = str(projection.get("projection_id") or "")
        expression = projection.get("expression")
        if name not in selected or not projection.get("logic_family") or not expression:
            continue
        tree, verbs = _split_structural_atoms(expression)
        if tree:
            vocabulary["closed_tokens"][name].update(_tokens(tree))
        for verb, parents in verbs.items():
            vocabulary["verb_parents"][name][verb].update(parents)
            document_verbs.add(verb)
    vocabulary["document_counts"].update(document_verbs)


def structural_column_token_sets(
    vocabulary: Mapping[str, Any], threshold: int,
) -> dict[str, set[str]]:
    """Return structural tokens when verbs below ``threshold`` become ``<open-verb>``."""

    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
        raise SkillCenterTrainingError("verb document threshold must be a positive integer")
    kept = {verb for verb, count in vocabulary["document_counts"].items() if count >= threshold}
    observed: dict[str, set[str]] = {
        name: set(tokens) for name, tokens in vocabulary["closed_tokens"].items()
    }
    for name, verbs in vocabulary["verb_parents"].items():
        open_paths: set[tuple[str, ...]] = set()
        for verb, parents in verbs.items():
            if verb in kept:
                for parent in parents:
                    observed[name].add(_presence_token(parent, verb))
            else:
                open_paths.update(parents)
        for parent in open_paths:
            observed[name].add(_presence_token(parent, _OPEN_VERB))
    return observed


def structural_columns_at_threshold(
    vocabulary: Mapping[str, Any], threshold: int,
) -> tuple[dict[str, int], int]:
    """Count structural columns when verbs below ``threshold`` become ``<open-verb>``."""

    observed = structural_column_token_sets(vocabulary, threshold)
    counts = {name: len(observed[name]) for name in observed}
    return counts, sum(counts.values())


def choose_min_verb_documents(
    vocabulary: Mapping[str, Any], *, max_columns: int = 4096,
) -> int:
    """Lowest document frequency at or above 2 whose structural columns fit."""

    if isinstance(max_columns, bool) or not isinstance(max_columns, int) or max_columns < 1:
        raise SkillCenterTrainingError("feature column bound must be a positive integer")
    counts = vocabulary["document_counts"]
    ceiling = max(counts.values(), default=1)
    _, collapsed = structural_columns_at_threshold(vocabulary, ceiling + 1)
    if collapsed > max_columns:
        raise SkillCenterTrainingError("closed structural atoms exceed the feature bound")
    _, baseline = structural_columns_at_threshold(vocabulary, _MIN_VERB_DOCUMENTS)
    if baseline <= max_columns:
        return _MIN_VERB_DOCUMENTS
    low = _MIN_VERB_DOCUMENTS + 1
    high = ceiling + 1
    selected = high
    while low <= high:
        mid = (low + high) // 2
        _, total = structural_columns_at_threshold(vocabulary, mid)
        if total <= max_columns:
            selected = mid
            high = mid - 1
        else:
            low = mid + 1
    return selected


def fit_kept_verbs(envelopes: Sequence[Any], *, min_documents: int = _MIN_VERB_DOCUMENTS) -> frozenset[str]:
    """Return verbs that occur in at least ``min_documents`` fitting sources."""

    if isinstance(min_documents, bool) or not isinstance(min_documents, int) or min_documents < 1:
        raise SkillCenterTrainingError("min_documents must be a positive integer")
    counts: Counter[str] = Counter()
    for envelope in envelopes:
        counts.update(_verb_leaves(envelope))
    return frozenset(verb for verb, count in counts.items() if count >= min_documents)


def structural_feature_envelopes(
    envelopes: Sequence[Any],
    *,
    kept_verbs: frozenset[str],
) -> list[Any]:
    """Copy envelopes so the trainer sees structural atoms, not raw identifier leaves.

    Stored campaign envelopes are not rewritten. The copy keeps the source
    digest, projection ids, and authority flags.
    """

    from ...formalization.autoencoder.domain_targets import DomainTargetEnvelope

    viewed = []
    for envelope in envelopes:
        payload = envelope.to_dict()
        projections = []
        for row in payload["projections"]:
            item = dict(row)
            expression = item.get("expression")
            if item.get("logic_family") and expression:
                item["expression"] = _structural_atom_tree(expression, kept_verbs=kept_verbs)
            projections.append(item)
        payload["projections"] = projections
        viewed.append(DomainTargetEnvelope.from_dict(payload))
    return viewed


def train_features(campaign_dir: Path, *, register: bool = True) -> dict[str, Any]:
    """Fit one native feature space on the pilot train partition."""

    enable_offline_environment()
    campaign_dir = Path(campaign_dir)
    _assert_pin(campaign_dir)
    if register and (campaign_dir / "candidate_staging").exists():
        raise SkillCenterTrainingError("candidate staging directory already exists")
    census = json.loads((campaign_dir / "vocabulary_census.json").read_text(encoding="utf-8"))
    if census.get("source_count", 0) > PILOT_SOURCE_LIMIT:
        raise SkillCenterTrainingError("pilot draw exceeds 1024 training sources")
    index = _read_parquet(campaign_dir / "target_index.parquet")
    train = _ready_partition(campaign_dir, index, TRAIN_PARTITION)
    tune = _ready_partition(campaign_dir, index, VALIDATION_PARTITION)
    if not train or not tune:
        raise SkillCenterTrainingError("train and validation envelopes are both required")
    _assert_disjoint_partitions(index)
    projection_ids = sorted(
        set(_common_family_projections(train)) & set(_common_family_projections(tune))
    )
    if not projection_ids:
        raise SkillCenterTrainingError("no projection is present on every train and validation envelope")
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ...formalization.autoencoder import domain_targets
    from ..schema import INTENT_IR_SCHEMA_VERSION

    kept_verbs = fit_kept_verbs(train)
    view_train = structural_feature_envelopes(train, kept_verbs=kept_verbs)
    view_tune = structural_feature_envelopes(tune, kept_verbs=kept_verbs)
    before = features.digest([item.to_dict() for item in train + tune])
    try:
        space = features.build_feature_space("intent_ir", projection_ids, view_train)
    except features.ProjectionFeatureError as exc:
        raise SkillCenterTrainingError(str(exc)) from exc
    if len(space["training_sources"]) > PILOT_SOURCE_LIMIT or len(space["columns"]) > features.MAX_FEATURES:
        raise SkillCenterTrainingError("feature space exceeds the trainer bound")
    adapter_sha = hashlib.sha256(Path(domain_targets.__file__).read_bytes()).hexdigest()
    contract = features.build_native_feature_contract(
        space,
        ir_schema=INTENT_IR_SCHEMA_VERSION,
        adapter_sha256=adapter_sha,
        latent_width=TRAIN_LATENT_WIDTH,
    )
    result = features.train_projection_features(
        contract,
        space,
        view_train,
        view_tune,
        epochs=TRAIN_EPOCHS,
        latent_width=TRAIN_LATENT_WIDTH,
        learning_rate=TRAIN_LEARNING_RATE,
        max_seconds=TRAIN_MAX_SECONDS,
        seed=TRAIN_SEED,
    )
    after = features.digest([item.to_dict() for item in train + tune])
    if before != after:
        raise SkillCenterTrainingError("training mutated input envelopes")
    _assert_training_report(result["report"])
    receipt: dict[str, Any] = {
        "schema": TRAIN_SCHEMA,
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "upstream_dataset_id": UPSTREAM_DATASET_ID,
        "upstream_revision": UPSTREAM_REVISION,
        "policy_version": SKILL_SOURCE_POLICY_VERSION,
        "normalizer_version": INTENT_NORMALIZER_VERSION,
        "split_digest": sha256_text((campaign_dir / "pilot_split.json").read_text(encoding="utf-8")),
        "vocabulary_census_sha256": sha256_text(
            (campaign_dir / "vocabulary_census.json").read_text(encoding="utf-8")
        ),
        "contract_sha256": result["report"]["contract_sha256"],
        "feature_space_sha256": result["report"]["feature_space_sha256"],
        "state_sha256": features.digest(result["state"]),
        "projection_ids": projection_ids,
        "excluded_projection_ids": space["excluded_projection_ids"],
        "vocabulary_policy": STRUCTURAL_VIEW_SCHEMA,
        "raw_column_count": census.get("column_count"),
        "view_column_count": len(space["columns"]),
        "kept_verb_count": len(kept_verbs),
        "min_verb_documents": _MIN_VERB_DOCUMENTS,
        "training_source_count": len(space["training_sources"]),
        "tuning_source_count": result["report"]["tuning_target_count"],
        "source_bound_is_per_call": True,
        "qualified": False,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "weights_downloaded": False,
        "lake_executed": False,
    }
    saved = {
        "contract": contract.to_dict(),
        "feature_space": space,
        "state": result["state"],
        "report": result["report"],
        "receipt": receipt,
        "structural_view": {
            "schema": STRUCTURAL_VIEW_SCHEMA,
            "min_verb_documents": _MIN_VERB_DOCUMENTS,
            "kept_verbs": sorted(kept_verbs),
        },
    }
    write_json(campaign_dir / "training_result.json", saved)
    if register:
        from ....duckdb_control.autoencoder_registry import AutoencoderRegistry

        staging = campaign_dir / "candidate_staging"
        if staging.exists():
            raise SkillCenterTrainingError("candidate staging directory already exists")
        with AutoencoderRegistry(
            campaign_dir / "registry.duckdb",
            campaign_dir / "registry_artifacts",
        ) as registry:
            registered = features.register_feature_candidate(
                registry, contract, space, result, staging, parent_version_id=None,
            )
        receipt["registry_version_id"] = registered["version_id"]
        receipt["variant_id"] = registered["variant_id"]
        write_json(campaign_dir / "training_receipt.json", receipt)
    else:
        write_json(campaign_dir / "training_receipt.json", receipt)
    return receipt


def evaluate_features(campaign_dir: Path) -> dict[str, Any]:
    """Score the deterministic compiler and the from-scratch feature state."""

    enable_offline_environment()
    campaign_dir = Path(campaign_dir)
    saved = json.loads((campaign_dir / "training_result.json").read_text(encoding="utf-8"))
    from ....optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ..formalize.compiler import IntentFormalizationCompiler
    from ..formalize.decompiler import IntentDecompiler

    contract = ModalityContract.from_dict(saved["contract"])
    space = saved["feature_space"]
    state = saved["state"]
    view_spec = saved.get("structural_view")
    if not isinstance(view_spec, dict) or view_spec.get("schema") != STRUCTURAL_VIEW_SCHEMA:
        raise SkillCenterTrainingError("training result has no structural atom view")
    kept_verbs = frozenset(str(item) for item in view_spec.get("kept_verbs") or ())
    index = _read_parquet(campaign_dir / "target_index.parquet")
    compiler = IntentFormalizationCompiler()
    decompiler = IntentDecompiler()
    deterministic = []
    for partition in (TEST_PARTITION, HELD_OUT_DOMAIN_PARTITION, HELD_OUT_TIME_REVISION_PARTITION):
        for row in index:
            if row["partition"] != partition:
                continue
            document = _load_document(campaign_dir, str(row["document_sha256"]))
            artifact = compiler.compile_document(document)
            review = decompiler.compare(document, artifact)
            deterministic.append(
                {
                    "document_id": document.document_id,
                    "partition": partition,
                    "compiler_valid": bool(artifact.diagnostics.valid),
                    "round_trip_passed": bool(review.passed),
                    "formula_count": len(artifact.formulas),
                }
            )
    inference_rows = []
    unknown_atoms = 0
    for partition in (TEST_PARTITION, HELD_OUT_DOMAIN_PARTITION, HELD_OUT_TIME_REVISION_PARTITION):
        envelopes = structural_feature_envelopes(
            _envelopes_covering(
                space["projection_ids"],
                _ready_partition(campaign_dir, index, partition),
            ),
            kept_verbs=kept_verbs,
        )
        if not envelopes:
            continue
        inferred = features.infer_projection_features(contract, space, state, envelopes)
        if inferred.get("decoded_formulas_generated") is not False:
            raise SkillCenterTrainingError("feature inference emitted formulas")
        if any(inferred.get(flag) is not False for flag in (*_AUTHORITY, "promotion_performed")):
            raise SkillCenterTrainingError("feature inference claimed authority")
        unknown_atoms += sum(int(item["unknown_atoms"]) for item in inferred["coverage"])
        inference_rows.append(
            {
                "partition": partition,
                "row_count": len(inferred["rows"]),
                "unknown_atoms": sum(int(item["unknown_atoms"]) for item in inferred["coverage"]),
            }
        )
    receipt = {
        "schema_version": EVAL_SCHEMA,
        "campaign": "skillcenter-intent-feature-eval/v1",
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "arms": {
            "deterministic_only": deterministic,
            "intent_from_scratch": inference_rows,
        },
        "legal_encoder_transfer": {
            "status": "not_run",
            "reason": "no Intent checkpoint policy has accepted a legal encoder",
        },
        "decoded_formulas_generated": False,
        "tool_authority_granted": False,
        "unknown_atoms": unknown_atoms,
        "qualified": False,
        "admitted": False,
        "formalized": False,
    }
    write_json(campaign_dir / "eval_receipt.json", receipt)
    return receipt


def report_reservoir_coverage(
    campaign_dir: Path,
    *,
    split_name: str = "corpus_split.json",
    census_name: str = "corpus_vocabulary_census.json",
    reservoir_limit: int = PILOT_SOURCE_LIMIT,
) -> dict[str, Any]:
    """Fit one 1,024-source basis and score the remaining train rows by inference.

    The gradient runs only on the reservoir. Remainder rows are a coverage
    report. This does not raise the trainer source cap and does not register
    a candidate.
    """

    if (
        isinstance(reservoir_limit, bool)
        or not isinstance(reservoir_limit, int)
        or not 1 <= reservoir_limit <= PILOT_SOURCE_LIMIT
    ):
        raise SkillCenterTrainingError("reservoir limit must stay within the 1024 source bound")
    enable_offline_environment()
    campaign_dir = Path(campaign_dir)
    _assert_pin(campaign_dir)
    census = json.loads((campaign_dir / census_name).read_text(encoding="utf-8"))
    manifest = json.loads((campaign_dir / split_name).read_text(encoding="utf-8"))
    assignments = {
        str(sample_id): str(partition)
        for sample_id, partition in dict(manifest["assignments"]).items()
    }
    index = _read_parquet(campaign_dir / "target_index.parquet")
    for row in index:
        document_id = str(row["document_id"])
        if assignments.get(document_id) != row["partition"]:
            raise SkillCenterTrainingError("target index does not match the split assignments")
    _assert_disjoint_partitions(index)
    train = _ready_partition(campaign_dir, index, TRAIN_PARTITION)
    tune = _ready_partition(campaign_dir, index, VALIDATION_PARTITION)
    if not train or not tune:
        raise SkillCenterTrainingError("train and validation envelopes are both required")
    ranked = _ranked_envelopes(train, seed=PILOT_SEED)
    reservoir = ranked[:reservoir_limit]
    remainder = ranked[reservoir_limit:]
    # The kernel accepts at most 1024 tuning rows per call. A corpus validation
    # partition is larger than that; Adam sees a ranked prefix, not every row.
    tune_batch = tune if len(tune) <= PILOT_SOURCE_LIMIT else _ranked_envelopes(tune, seed=PILOT_SEED)[:PILOT_SOURCE_LIMIT]
    projection_ids = sorted(
        set(_common_family_projections(reservoir)) & set(_common_family_projections(tune_batch))
    )
    if not projection_ids:
        raise SkillCenterTrainingError("no projection is present on every reservoir and validation envelope")
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ...formalization.autoencoder import domain_targets
    from ..schema import INTENT_IR_SCHEMA_VERSION

    kept_verbs = fit_kept_verbs(reservoir)
    view_reservoir = structural_feature_envelopes(reservoir, kept_verbs=kept_verbs)
    view_tune = structural_feature_envelopes(tune_batch, kept_verbs=kept_verbs)
    try:
        space = features.build_feature_space("intent_ir", projection_ids, view_reservoir)
    except features.ProjectionFeatureError as exc:
        raise SkillCenterTrainingError(str(exc)) from exc
    if space["schema"] != "native-projection-feature-space/v1":
        raise SkillCenterTrainingError("reservoir fit must stay on feature space v1")
    if len(space["training_sources"]) > reservoir_limit or len(space["columns"]) > features.MAX_FEATURES:
        raise SkillCenterTrainingError("feature space exceeds the trainer bound")
    adapter_sha = hashlib.sha256(Path(domain_targets.__file__).read_bytes()).hexdigest()
    contract = features.build_native_feature_contract(
        space,
        ir_schema=INTENT_IR_SCHEMA_VERSION,
        adapter_sha256=adapter_sha,
        latent_width=TRAIN_LATENT_WIDTH,
    )
    result = features.train_projection_features(
        contract,
        space,
        view_reservoir,
        view_tune,
        epochs=TRAIN_EPOCHS,
        latent_width=TRAIN_LATENT_WIDTH,
        learning_rate=TRAIN_LEARNING_RATE,
        max_seconds=TRAIN_MAX_SECONDS,
        seed=TRAIN_SEED,
    )
    _assert_training_report(result["report"])
    unknown_atoms = 0
    inferred_rows = 0
    uncovered = 0
    for start in range(0, len(remainder), PILOT_SOURCE_LIMIT):
        batch = remainder[start : start + PILOT_SOURCE_LIMIT]
        covered = _envelopes_covering(space["projection_ids"], batch)
        uncovered += len(batch) - len(covered)
        if not covered:
            continue
        try:
            inferred = features.infer_projection_features(
                contract,
                space,
                result["state"],
                structural_feature_envelopes(covered, kept_verbs=kept_verbs),
            )
        except features.ProjectionFeatureError as exc:
            raise SkillCenterTrainingError(str(exc)) from exc
        if inferred.get("decoded_formulas_generated") is not False:
            raise SkillCenterTrainingError("feature inference emitted formulas")
        if any(inferred.get(flag) is not False for flag in (*_AUTHORITY, "promotion_performed")):
            raise SkillCenterTrainingError("feature inference claimed authority")
        unknown_atoms += sum(int(item["unknown_atoms"]) for item in inferred["coverage"])
        inferred_rows += len(inferred["rows"])
    receipt = {
        "schema": "skillcenter-intent-reservoir-coverage/v1",
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "split_digest": sha256_text((campaign_dir / split_name).read_text(encoding="utf-8")),
        "vocabulary_census_sha256": sha256_text((campaign_dir / census_name).read_text(encoding="utf-8")),
        "vocabulary_policy": STRUCTURAL_VIEW_SCHEMA,
        "raw_column_count": census.get("column_count"),
        "view_column_count": len(space["columns"]),
        "kept_verb_count": len(kept_verbs),
        "feature_space_schema": space["schema"],
        "reservoir_source_count": len(space["training_sources"]),
        "validation_source_count": len(tune),
        "tune_source_count": len(tune_batch),
        "remainder_source_count": len(remainder),
        "inferred_source_count": inferred_rows,
        "uncovered_source_count": uncovered,
        "unknown_atoms": unknown_atoms,
        "gradient_applied_to_reservoir_only": True,
        "full_corpus_gradient": False,
        "decoded_formulas_generated": False,
        "tool_authority_granted": False,
        "qualified": False,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "weights_downloaded": False,
        "lake_executed": False,
        "state_sha256": features.digest(result["state"]),
        "contract_sha256": result["report"]["contract_sha256"],
    }
    write_json(
        campaign_dir / "reservoir_feature_state.json",
        {
            "contract": contract.to_dict(),
            "feature_space": space,
            "state": result["state"],
            "report": result["report"],
        },
    )
    write_json(campaign_dir / "reservoir_coverage.json", receipt)
    return receipt


def report_eligible_coverage(
    campaign_dir: Path,
    *,
    split_name: str = "corpus_split.json",
    state_name: str = "reservoir_feature_state.json",
) -> dict[str, Any]:
    """Score ready envelopes that were not reservoir gradient steps.

    The saved reservoir state is read and checked. This does not train, does
    not register a candidate, and does not rewrite that state. A second column
    count fits the structural view on every covering ready envelope. That count
    is the gate for a later wider contract. It is not itself a training run.
    """

    enable_offline_environment()
    campaign_dir = Path(campaign_dir)
    _assert_pin(campaign_dir)
    state_path = campaign_dir / state_name
    if not state_path.is_file():
        raise SkillCenterTrainingError("reservoir feature state is missing")
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    from ....optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

    space = saved.get("feature_space")
    if not isinstance(space, dict) or space.get("schema") != "native-projection-feature-space/v1":
        raise SkillCenterTrainingError("coverage requires the saved feature space v1")
    projection_ids = [str(name) for name in space.get("projection_ids") or ()]
    training_sources = {str(item) for item in space.get("training_sources") or ()}
    if not projection_ids or not training_sources:
        raise SkillCenterTrainingError("saved feature space has no projections or sources")
    if len(training_sources) > PILOT_SOURCE_LIMIT or len(space.get("columns") or ()) > features.MAX_FEATURES:
        raise SkillCenterTrainingError("saved feature space exceeds the trainer bound")
    contract = ModalityContract.from_dict(saved["contract"])
    state = saved["state"]
    manifest = json.loads((campaign_dir / split_name).read_text(encoding="utf-8"))
    assignments = {
        str(sample_id): str(partition)
        for sample_id, partition in dict(manifest["assignments"]).items()
    }
    index = _read_parquet(campaign_dir / "target_index.parquet")
    for row in index:
        document_id = str(row["document_id"])
        if assignments.get(document_id) != row["partition"]:
            raise SkillCenterTrainingError("target index does not match the split assignments")
    _assert_disjoint_partitions(index)
    identities, reservoir_counts, full_counts = _ready_feature_identities(
        campaign_dir, index, projection_ids, training_sources,
    )
    if {item["source_digest"] for item in identities if item["source_digest"] in training_sources} != training_sources:
        raise SkillCenterTrainingError("reservoir training sources are not a subset of the ready envelopes")
    reservoir_verbs = frozenset(
        verb for verb, count in reservoir_counts.items() if count >= _MIN_VERB_DOCUMENTS
    )
    full_verbs = frozenset(verb for verb, count in full_counts.items() if count >= _MIN_VERB_DOCUMENTS)
    reservoir_envelopes = _ranked_envelopes(
        _load_envelopes(
            campaign_dir,
            [item["file_digest"] for item in identities if item["source_digest"] in training_sources],
        ),
        seed=PILOT_SEED,
    )
    try:
        rebuilt = features.build_feature_space("intent_ir", projection_ids, structural_feature_envelopes(
            reservoir_envelopes, kept_verbs=reservoir_verbs,
        ))
    except features.ProjectionFeatureError as exc:
        raise SkillCenterTrainingError(str(exc)) from exc
    if features.digest(rebuilt) != features.digest(space):
        raise SkillCenterTrainingError("reservoir feature space does not match the structural view")
    validation_ranked = sorted(
        (item for item in identities if item["partition"] == VALIDATION_PARTITION and item["covers"]),
        key=lambda item: hashlib.sha256(
            f"{PILOT_SEED}\x1f{item['source_digest']}".encode("utf-8")
        ).hexdigest(),
    )
    tune_sources = {item["source_digest"] for item in validation_ranked[:PILOT_SOURCE_LIMIT]}
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for item in identities:
        if not item["covers"]:
            continue
        source = item["source_digest"]
        if source in training_sources:
            role = "gradient"
        elif source in tune_sources:
            role = "tuning_batch"
        elif item["partition"] == TRAIN_PARTITION:
            role = "train_remainder"
        else:
            role = "coverage"
        grouped[(item["partition"], role)].append(item)
    buckets = _infer_coverage_groups(
        campaign_dir, features, contract, space, state, grouped, reservoir_verbs,
    )
    column_counts, column_total = _structural_column_census(
        campaign_dir,
        [item for item in identities if item["covers"]],
        projection_ids,
        full_verbs,
    )
    heaviest = [
        {"projection_id": name, "column_count": column_counts[name]}
        for name in sorted(column_counts, key=lambda name: (-column_counts[name], name))[:8]
    ]
    inferred_rows = sum(bucket["inferred_count"] for bucket in buckets)
    no_coverage = sum(bucket["no_feature_coverage_count"] for bucket in buckets)
    reasons: Counter[str] = Counter()
    for bucket in buckets:
        reasons.update(bucket["reasons"])
    receipt = {
        "schema": ELIGIBLE_COVERAGE_SCHEMA,
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "vocabulary_policy": STRUCTURAL_VIEW_SCHEMA,
        "feature_space_schema": space["schema"],
        "feature_space_sha256": features.digest(space),
        "state_sha256": features.digest(state),
        "reservoir_state_sha256": sha256_file(state_path),
        "reservoir_source_count": len(training_sources),
        "reservoir_kept_verb_count": len(reservoir_verbs),
        "reservoir_view_column_count": len(space["columns"]),
        "ready_row_count": len(identities),
        "uncovered_projection_count": sum(not item["covers"] for item in identities),
        "gradient_source_count": len(training_sources),
        "tuning_batch_source_count": sum(
            bucket["ready_count"] for bucket in buckets if bucket["role"] == "tuning_batch"
        ),
        "train_remainder_source_count": sum(
            bucket["ready_count"] for bucket in buckets if bucket["role"] == "train_remainder"
        ),
        "coverage_source_count": sum(
            bucket["ready_count"] for bucket in buckets if bucket["role"] == "coverage"
        ),
        "inferred_source_count": inferred_rows,
        "no_feature_coverage_count": no_coverage,
        "rows_with_unknown_atoms": sum(bucket["rows_with_unknown_atoms"] for bucket in buckets),
        "known_atoms": sum(bucket["known_atoms"] for bucket in buckets),
        "unknown_atoms": sum(bucket["unknown_atoms"] for bucket in buckets),
        "no_feature_coverage_reasons": dict(reasons.most_common(8)),
        "partitions": [
            {key: value for key, value in bucket.items() if key != "reasons"}
            for bucket in sorted(buckets, key=lambda item: (item["partition"], item["role"]))
        ],
        "full_ready_source_count": sum(item["covers"] for item in identities),
        "full_ready_kept_verb_count": len(full_verbs),
        "full_ready_view_column_count": column_total,
        "full_ready_within_feature_bound": 1 <= column_total <= features.MAX_FEATURES,
        "full_ready_within_source_bound": sum(item["covers"] for item in identities) <= PILOT_SOURCE_LIMIT,
        "full_ready_projection_column_counts": column_counts,
        "full_ready_heaviest_projections": heaviest,
        "gradient_applied_to_reservoir_only": True,
        "full_corpus_gradient": False,
        "training_executed": False,
        "decoded_formulas_generated": False,
        "tool_authority_granted": False,
        "qualified": False,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "weights_downloaded": False,
        "lake_executed": False,
    }
    write_json(campaign_dir / "eligible_coverage.json", receipt)
    return receipt


def report_full_ready_vocabulary(
    campaign_dir: Path,
    *,
    split_name: str = "corpus_split.json",
    census_name: str = "corpus_vocabulary_census.json",
    max_columns: int | None = None,
) -> dict[str, Any]:
    """Choose a verb frequency that lets every ready envelope share one vocabulary.

    The threshold is fit on every ready envelope that carries the census
    projections. That population includes validation and holdout rows, so this
    receipt is a column gate. It does not train, register, or replace the
    pilot's ``skillcenter-structural-atom-view/v1`` candidate.
    """

    enable_offline_environment()
    campaign_dir = Path(campaign_dir)
    _assert_pin(campaign_dir)
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

    if max_columns is None:
        max_columns = features.MAX_FEATURES
    census = json.loads((campaign_dir / census_name).read_text(encoding="utf-8"))
    projection_ids = [str(name) for name in census.get("projection_ids") or ()]
    if len(projection_ids) != len(set(projection_ids)) or not projection_ids:
        raise SkillCenterTrainingError("vocabulary census has no projection ids")
    manifest = json.loads((campaign_dir / split_name).read_text(encoding="utf-8"))
    assignments = {
        str(sample_id): str(partition)
        for sample_id, partition in dict(manifest["assignments"]).items()
    }
    index = _read_parquet(campaign_dir / "target_index.parquet")
    for row in index:
        document_id = str(row["document_id"])
        if assignments.get(document_id) != row["partition"]:
            raise SkillCenterTrainingError("target index does not match the split assignments")
    _assert_disjoint_partitions(index)
    vocabulary = _empty_structural_vocabulary(projection_ids)
    ready_rows = 0
    uncovered = 0
    seen: set[str] = set()
    required = set(projection_ids)
    for row in index:
        if not row.get("ready") or not row.get("source_digest"):
            continue
        envelope = _load_envelope(campaign_dir, str(row["source_digest"]))
        if envelope.digest != str(row["source_digest"]):
            raise SkillCenterTrainingError("envelope file digest does not match the target index")
        assert_envelope_authority(envelope.to_dict())
        source = envelope.source_digest
        if source in seen:
            raise SkillCenterTrainingError("duplicate source in ready envelopes")
        seen.add(source)
        names = {
            str(item["projection_id"])
            for item in envelope.to_dict()["projections"]
            if item.get("logic_family") and item.get("expression")
        }
        ready_rows += 1
        if not required <= names:
            uncovered += 1
            continue
        _accumulate_structural_vocabulary(vocabulary, envelope, projection_ids)
        if ready_rows % _INDEX_CHECKPOINT_EVERY == 0:
            _note_checkpoint("full_ready_vocabulary", ready_rows)
    if ready_rows == uncovered:
        raise SkillCenterTrainingError("no ready envelope covers the census projections")
    threshold = choose_min_verb_documents(vocabulary, max_columns=max_columns)
    baseline_counts, baseline_total = structural_columns_at_threshold(vocabulary, _MIN_VERB_DOCUMENTS)
    selected_counts, selected_total = structural_columns_at_threshold(vocabulary, threshold)
    prior = campaign_dir / "eligible_coverage.json"
    if prior.is_file() and threshold >= _MIN_VERB_DOCUMENTS:
        recorded = json.loads(prior.read_text(encoding="utf-8"))
        recorded_columns = recorded.get("full_ready_projection_column_counts")
        if (
            recorded.get("vocabulary_policy") == STRUCTURAL_VIEW_SCHEMA
            and recorded.get("full_ready_view_column_count") not in (None, baseline_total)
        ):
            raise SkillCenterTrainingError(
                "verb threshold census disagrees with the recorded full-ready column count"
            )
        if isinstance(recorded_columns, dict) and recorded_columns != baseline_counts:
            if recorded.get("vocabulary_policy") == STRUCTURAL_VIEW_SCHEMA:
                raise SkillCenterTrainingError(
                    "verb threshold census disagrees with the recorded projection columns"
                )
    curve = []
    for sample in (2, 3, 5, 10, 20, 50, 100, threshold):
        if any(point["min_verb_documents"] == sample for point in curve):
            continue
        counts, total = (
            (baseline_counts, baseline_total)
            if sample == _MIN_VERB_DOCUMENTS
            else (selected_counts, selected_total)
            if sample == threshold
            else structural_columns_at_threshold(vocabulary, sample)
        )
        curve.append(
            {
                "min_verb_documents": sample,
                "kept_verb_count": sum(
                    count >= sample for count in vocabulary["document_counts"].values()
                ),
                "view_column_count": total,
                "within_feature_bound": 1 <= total <= max_columns,
            }
        )
    heaviest = [
        {"projection_id": name, "column_count": selected_counts[name]}
        for name in sorted(selected_counts, key=lambda name: (-selected_counts[name], name))
    ]
    receipt = {
        "schema": FULL_READY_VOCABULARY_SCHEMA,
        "vocabulary_policy": STRUCTURAL_VIEW_V2_SCHEMA,
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "selection_rule": (
            "lowest min_verb_documents >= 2 such that structural columns on every "
            f"ready covering envelope are <= {max_columns}"
        ),
        "fitting_population": "all_ready_covering_envelopes",
        "min_verb_documents": threshold,
        "baseline_min_verb_documents": _MIN_VERB_DOCUMENTS,
        "baseline_kept_verb_count": sum(
            count >= _MIN_VERB_DOCUMENTS for count in vocabulary["document_counts"].values()
        ),
        "baseline_view_column_count": baseline_total,
        "kept_verb_count": sum(
            count >= threshold for count in vocabulary["document_counts"].values()
        ),
        "unique_verb_count": len(vocabulary["document_counts"]),
        "hapax_verb_count": sum(count == 1 for count in vocabulary["document_counts"].values()),
        "view_column_count": selected_total,
        "within_feature_bound": 1 <= selected_total <= max_columns,
        "within_source_bound": (ready_rows - uncovered) <= PILOT_SOURCE_LIMIT,
        "max_columns": max_columns,
        "projection_ids": projection_ids,
        "projection_column_counts": selected_counts,
        "heaviest_projections": heaviest,
        "threshold_curve": curve,
        "ready_row_count": ready_rows,
        "fitting_source_count": ready_rows - uncovered,
        "uncovered_projection_count": uncovered,
        "feature_space_schema": "native-projection-feature-space/v1",
        "training_executed": False,
        "full_corpus_gradient": False,
        "decoded_formulas_generated": False,
        "tool_authority_granted": False,
        "qualified": False,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "weights_downloaded": False,
        "lake_executed": False,
    }
    write_json(campaign_dir / "full_ready_vocabulary.json", receipt)
    return receipt


def _write_json_durable(path: Path, value: Mapping[str, Any]) -> None:
    raw = canonical_json(value).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _v2_configuration(
    *,
    epochs: int,
    latent_width: int,
    learning_rate: float,
    max_seconds: float,
    seed: int,
    minibatch_size: int,
    tune_limit: int,
) -> dict[str, Any]:
    return {
        "epochs": epochs,
        "latent_width": latent_width,
        "learning_rate": float(learning_rate),
        "max_seconds": float(max_seconds),
        "seed": seed,
        "minibatch_size": minibatch_size,
        "tune_limit": tune_limit,
    }


def _snapshot_campaign_files(campaign_dir: Path) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for name in _V2_UNTOUCHED:
        path = campaign_dir / name
        snapshot[name] = sha256_file(path) if path.is_file() else None
    return snapshot


def _assert_campaign_files_unchanged(campaign_dir: Path, snapshot: Mapping[str, str | None]) -> None:
    if _snapshot_campaign_files(campaign_dir) != snapshot:
        raise SkillCenterTrainingError("v2 training changed an existing campaign receipt")


def _finished_streamed_receipt(path: Path, configuration: Mapping[str, Any]) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != STREAMED_TRAIN_SCHEMA:
        raise SkillCenterTrainingError("v2 training receipt schema is not recognized")
    for name in (
        *_AUTHORITY,
        "promotion_performed",
        "heldout_canary",
        "lake_executed",
        "weights_downloaded",
        "full_corpus_gradient",
        "full_ready_gradient",
        "tool_authority_granted",
        "decoded_formulas_generated",
    ):
        if receipt.get(name) is not False:
            raise SkillCenterTrainingError(f"v2 training receipt {name} must stay false")
    if receipt.get("training_executed") is not True or receipt.get("registered") is not False:
        raise SkillCenterTrainingError("v2 training receipt does not describe an unregistered training run")
    if receipt.get("legal_encoder_transfer") != "not_run":
        raise SkillCenterTrainingError("v2 training receipt must leave legal encoder transfer not_run")
    if receipt.get("embedding_model_id") != "native-projection-features":
        raise SkillCenterTrainingError("v2 training receipt embedding model is not the native projection features")
    if receipt.get("configuration") != configuration:
        raise SkillCenterTrainingError("v2 training receipt already exists for a different configuration")
    return receipt


def _projection_descriptor(projection: Mapping[str, Any]) -> dict[str, Any]:
    return {key: projection.get(key) for key in _DESCRIPTOR_KEYS}


def _v2_rank(source_digest: str) -> str:
    return hashlib.sha256(f"{PILOT_SEED}\x1f{source_digest}".encode("utf-8")).hexdigest()


def _collect_streamed_identities(
    campaign_dir: Path,
    index: Sequence[Mapping[str, Any]],
    projection_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    required = set(projection_ids)
    known_partitions = {
        TRAIN_PARTITION,
        VALIDATION_PARTITION,
        *_HOLDOUT_PARTITIONS,
    }
    identities: list[dict[str, Any]] = []
    descriptors: dict[str, Any] = {}
    seen: set[str] = set()
    not_ready = 0
    for row in index:
        if not row.get("ready") or not row.get("source_digest"):
            not_ready += 1
            continue
        partition = str(row["partition"])
        if partition not in known_partitions:
            raise SkillCenterTrainingError("target partition is not a campaign partition")
        envelope = _load_envelope(campaign_dir, str(row["source_digest"]))
        if envelope.digest != str(row["source_digest"]):
            raise SkillCenterTrainingError("envelope file digest does not match the target index")
        payload = envelope.to_dict()
        assert_envelope_authority(payload)
        source = payload.get("source_digest")
        if not isinstance(source, str) or source in seen:
            raise SkillCenterTrainingError("duplicate source in ready envelopes")
        seen.add(source)
        names = {
            str(item.get("projection_id") or "")
            for item in payload["projections"]
            if item.get("logic_family") and item.get("expression")
        }
        covers = required <= names
        if covers:
            for projection in payload["projections"]:
                name = str(projection.get("projection_id") or "")
                if name not in required or not projection.get("logic_family") or not projection.get("expression"):
                    continue
                descriptor = _projection_descriptor(projection)
                previous = descriptors.get(name)
                if previous is not None and previous != descriptor:
                    raise SkillCenterTrainingError("projection semantics changed between rows")
                descriptors[name] = descriptor
        identities.append(
            {
                "partition": partition,
                "file_digest": envelope.digest,
                "source_digest": source,
                "covers": covers,
                "rank": _v2_rank(source),
            }
        )
        if len(identities) % _INDEX_CHECKPOINT_EVERY == 0:
            _note_checkpoint("v2_identities", len(identities))
    if set(descriptors) != required:
        raise SkillCenterTrainingError("projection descriptor is missing")
    return identities, descriptors, not_ready


def _fit_streamed_vocabulary(
    campaign_dir: Path,
    gradient_items: Sequence[Mapping[str, Any]],
    projection_ids: Sequence[str],
):
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

    vocabulary = _empty_structural_vocabulary(projection_ids)
    excluded: set[str] = set()
    selected = set(projection_ids)
    for ordinal, item in enumerate(gradient_items, start=1):
        envelope = _load_envelope(campaign_dir, str(item["file_digest"]))
        if envelope.digest != item["file_digest"] or envelope.source_digest != item["source_digest"]:
            raise SkillCenterTrainingError("envelope identity changed while streaming features")
        payload = envelope.to_dict()
        assert_envelope_authority(payload)
        for projection in payload["projections"]:
            name = str(projection.get("projection_id") or "")
            if name and name not in selected:
                excluded.add(name)
        _accumulate_structural_vocabulary(vocabulary, envelope, projection_ids)
        if ordinal % _INDEX_CHECKPOINT_EVERY == 0:
            _note_checkpoint("v2_vocabulary", ordinal)
    threshold = choose_min_verb_documents(vocabulary, max_columns=features.MAX_FEATURES)
    token_sets = structural_column_token_sets(vocabulary, threshold)
    if any(not token_sets[name] for name in projection_ids):
        raise SkillCenterTrainingError("structural view produced an empty projection")
    columns = sorted([name, token] for name in projection_ids for token in token_sets[name])
    if not 1 <= len(columns) <= features.MAX_FEATURES:
        raise SkillCenterTrainingError("structural view exceeds the feature column bound")
    kept = frozenset(
        verb for verb, count in vocabulary["document_counts"].items() if count >= threshold
    )
    curve = []
    for sample in (2, 3, 5, 10, 12, 20, 50, 100, threshold):
        if any(point["min_verb_documents"] == sample for point in curve):
            continue
        _counts, total = structural_columns_at_threshold(vocabulary, sample)
        curve.append(
            {
                "min_verb_documents": sample,
                "kept_verb_count": sum(
                    count >= sample for count in vocabulary["document_counts"].values()
                ),
                "view_column_count": total,
                "within_feature_bound": 1 <= total <= features.MAX_FEATURES,
            }
        )
    summary = {
        "threshold": threshold,
        "kept_verb_count": len(kept),
        "unique_verb_count": len(vocabulary["document_counts"]),
        "hapax_verb_count": sum(count == 1 for count in vocabulary["document_counts"].values()),
        "projection_column_counts": {name: len(token_sets[name]) for name in projection_ids},
        "curve": curve,
        "excluded_projection_ids": sorted(excluded),
    }
    return columns, kept, summary


def _stream_feature_matrix(
    campaign_dir: Path,
    items: Sequence[Mapping[str, Any]],
    provisional: Mapping[str, Any],
    kept_verbs: frozenset[str],
    *,
    label: str,
    require_closed: bool,
):
    import numpy as np

    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features_v2 import (
        MAX_MINIBATCH,
        update_target_digest,
    )

    if not items:
        raise SkillCenterTrainingError("feature matrix requires at least one source")
    width = len(provisional["columns"])
    matrix = np.empty((len(items), width), dtype=np.float64)
    ids: list[str] = []
    seen = np.zeros(width, dtype=bool)
    known = 0
    unknown = 0
    hasher = hashlib.sha256()
    cursor = 0
    for start in range(0, len(items), MAX_MINIBATCH):
        batch_items = list(items[start : start + MAX_MINIBATCH])
        envelopes = []
        for item in batch_items:
            envelope = _load_envelope(campaign_dir, str(item["file_digest"]))
            if envelope.digest != item["file_digest"] or envelope.source_digest != item["source_digest"]:
                raise SkillCenterTrainingError("envelope identity changed while streaming features")
            assert_envelope_authority(envelope.to_dict())
            envelopes.append(envelope)
        viewed = structural_feature_envelopes(envelopes, kept_verbs=kept_verbs)
        for envelope in viewed:
            update_target_digest(hasher, envelope)
        try:
            values, sources, coverage = features._matrix(provisional, viewed)
        except features.ProjectionFeatureError as exc:
            raise SkillCenterTrainingError(str(exc)) from exc
        expected = [str(item["source_digest"]) for item in batch_items]
        if sources != expected:
            raise SkillCenterTrainingError("feature matrix row order does not match the ranked sources")
        block = np.asarray(values, dtype=np.float64)
        if block.shape != (len(batch_items), width) or not bool(np.isfinite(block).all()):
            raise SkillCenterTrainingError("feature matrix does not match the fitted columns")
        seen |= np.any(block != 0.0, axis=0)
        matrix[cursor : cursor + len(batch_items)] = block
        cursor += len(batch_items)
        ids.extend(sources)
        known += sum(int(item["known_atoms"]) for item in coverage)
        unknown += sum(int(item["unknown_atoms"]) for item in coverage)
        if cursor % _INDEX_CHECKPOINT_EVERY == 0:
            _note_checkpoint(f"v2_{label}", cursor)
    if require_closed and unknown:
        raise SkillCenterTrainingError(
            f"gradient view produced atoms outside the fitted columns ({unknown})"
        )
    if require_closed and not bool(seen.all()):
        missing = int((~seen).sum())
        raise SkillCenterTrainingError(
            f"structural view columns were not observed on the gradient rows ({missing})"
        )
    print(
        f"v2_{label} rows={cursor} columns={width} unknown_atoms={unknown}",
        file=sys.stderr,
        flush=True,
    )
    return matrix, ids, known, unknown, hasher.hexdigest()


def _infer_v2_holdout(
    campaign_dir: Path,
    items: Sequence[Mapping[str, Any]],
    space: Mapping[str, Any],
    state: Mapping[str, Any],
    kept_verbs: frozenset[str],
) -> dict[str, Any]:
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features_v2 import (
        MAX_MINIBATCH,
        ProjectionFeatureError,
        infer_streamed_projection_features,
    )

    inferred_rows = 0
    known = 0
    unknown = 0
    unknown_rows = 0
    failures: list[str] = []
    projection_count = len(space["projection_ids"])

    def consume(inferred: Mapping[str, Any]) -> None:
        nonlocal inferred_rows, known, unknown, unknown_rows
        if inferred.get("training_executed") is not False or inferred.get("decoded_formulas_generated") is not False:
            raise SkillCenterTrainingError("feature inference trained or emitted formulas")
        if any(inferred.get(flag) is not False for flag in (*_AUTHORITY, "promotion_performed")):
            raise SkillCenterTrainingError("feature inference claimed authority")
        coverage = list(inferred["coverage"])
        if projection_count == 0 or len(coverage) % projection_count != 0:
            raise SkillCenterTrainingError("feature inference coverage does not match the projections")
        inferred_rows += len(inferred["rows"])
        for offset in range(0, len(coverage), projection_count):
            chunk = coverage[offset : offset + projection_count]
            known += sum(int(item["known_atoms"]) for item in chunk)
            unknown += sum(int(item["unknown_atoms"]) for item in chunk)
            if any(int(item["unknown_atoms"]) > 0 for item in chunk):
                unknown_rows += 1

    def walk(group: Sequence[Mapping[str, Any]]) -> None:
        if not group:
            return
        envelopes = []
        for item in group:
            envelope = _load_envelope(campaign_dir, str(item["file_digest"]))
            if envelope.digest != item["file_digest"] or envelope.source_digest != item["source_digest"]:
                raise SkillCenterTrainingError("envelope identity changed while streaming features")
            assert_envelope_authority(envelope.to_dict())
            envelopes.append(envelope)
        try:
            viewed = structural_feature_envelopes(envelopes, kept_verbs=kept_verbs)
            inferred = infer_streamed_projection_features(space, state, viewed)
        except (SkillCenterTrainingError, ProjectionFeatureError) as exc:
            text = str(exc).splitlines()[0][:240]
            if "authority" in text or "formula" in text:
                raise SkillCenterTrainingError(text) from exc
            if len(group) == 1:
                failures.append(text)
                return
            mid = len(group) // 2
            walk(group[:mid])
            walk(group[mid:])
            return
        consume(inferred)

    for start in range(0, len(items), MAX_MINIBATCH):
        walk(list(items[start : start + MAX_MINIBATCH]))
        done = min(start + MAX_MINIBATCH, len(items))
        if done % _INDEX_CHECKPOINT_EVERY == 0 or done == len(items):
            _note_checkpoint("v2_holdout", done)
    if items and inferred_rows == 0 and len(failures) == len(items):
        raise SkillCenterTrainingError("holdout inference failed for every ready row")
    return {
        "inferred_count": inferred_rows,
        "no_feature_coverage_count": len(failures),
        "known_atoms": known,
        "unknown_atoms": unknown,
        "rows_with_unknown_atoms": unknown_rows,
        "reasons": dict(Counter(failures).most_common(8)),
    }


def train_streamed_features(
    campaign_dir: Path,
    *,
    split_name: str = "corpus_split.json",
    census_name: str = "corpus_vocabulary_census.json",
    tune_limit: int = PILOT_SOURCE_LIMIT,
    minibatch_size: int = PILOT_SOURCE_LIMIT,
    epochs: int = TRAIN_EPOCHS,
    latent_width: int = TRAIN_LATENT_WIDTH,
    learning_rate: float = TRAIN_LEARNING_RATE,
    max_seconds: float = V2_MAX_SECONDS,
    seed: int = TRAIN_SEED,
) -> dict[str, Any]:
    """Fit native-projection-feature-space/v2 on the gradient population.

    Gradient rows are ready covering envelopes in train, plus ready covering
    validation envelopes outside the ranked tune batch. Test and held-out
    partitions are neither gradient steps nor part of the verb-threshold fit.
    The run does not register a candidate and does not replace the pilot receipts.
    """

    if isinstance(tune_limit, bool) or not isinstance(tune_limit, int) or not 1 <= tune_limit <= PILOT_SOURCE_LIMIT:
        raise SkillCenterTrainingError("tune batch must stay within the 1024 source bound")
    if (
        isinstance(minibatch_size, bool)
        or not isinstance(minibatch_size, int)
        or not 1 <= minibatch_size <= PILOT_SOURCE_LIMIT
    ):
        raise SkillCenterTrainingError("minibatch size must stay within the 1024 row bound")
    if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= 32:
        raise SkillCenterTrainingError("epochs are outside the trainer bound")
    if isinstance(latent_width, bool) or not isinstance(latent_width, int) or not 1 <= latent_width <= 64:
        raise SkillCenterTrainingError("latent width is outside the trainer bound")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise SkillCenterTrainingError("invalid local seed")
    if (
        isinstance(learning_rate, bool)
        or type(learning_rate) not in (int, float)
        or learning_rate != learning_rate
        or not 0 < float(learning_rate) <= 0.1
    ):
        raise SkillCenterTrainingError("learning rate must be finite within (0, .1]")
    if (
        isinstance(max_seconds, bool)
        or type(max_seconds) not in (int, float)
        or max_seconds != max_seconds
        or not 0 < float(max_seconds) <= 14400
    ):
        raise SkillCenterTrainingError("v2 training deadline exceeds its bound")
    learning_rate = float(learning_rate)
    max_seconds = float(max_seconds)
    configuration = _v2_configuration(
        epochs=epochs,
        latent_width=latent_width,
        learning_rate=learning_rate,
        max_seconds=max_seconds,
        seed=seed,
        minibatch_size=minibatch_size,
        tune_limit=tune_limit,
    )
    enable_offline_environment()
    campaign_dir = Path(campaign_dir)
    _assert_pin(campaign_dir)
    receipt_path = campaign_dir / "v2_training_receipt.json"
    if receipt_path.is_file():
        return _finished_streamed_receipt(receipt_path, configuration)
    if _disk_free(campaign_dir) < DISK_RESERVE_BYTES:
        raise SkillCenterTrainingError("disk reserve would fall below 20GiB")
    started = time.monotonic()
    untouched = _snapshot_campaign_files(campaign_dir)
    staging = campaign_dir / "candidate_staging"
    staging_existed = staging.exists()
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ....optimizers.logic_theorem_optimizer import autoencoder_projection_features_v2 as streamed

    census_path = campaign_dir / census_name
    if not census_path.is_file():
        raise SkillCenterTrainingError("vocabulary census is missing")
    census = json.loads(census_path.read_text(encoding="utf-8"))
    projection_ids = [str(name) for name in census.get("projection_ids") or ()]
    if not projection_ids or len(projection_ids) != len(set(projection_ids)):
        raise SkillCenterTrainingError("vocabulary census has no projection ids")
    manifest = json.loads((campaign_dir / split_name).read_text(encoding="utf-8"))
    assignments = {
        str(sample_id): str(partition)
        for sample_id, partition in dict(manifest["assignments"]).items()
    }
    index = _read_parquet(campaign_dir / "target_index.parquet")
    for row in index:
        if assignments.get(str(row["document_id"])) != row["partition"]:
            raise SkillCenterTrainingError("target index does not match the split assignments")
    _assert_disjoint_partitions(index)
    identities, descriptors, not_ready = _collect_streamed_identities(
        campaign_dir, index, projection_ids,
    )
    def by_rank(item: Mapping[str, Any]) -> tuple[str, str]:
        return (str(item["rank"]), str(item["source_digest"]))

    train_items = sorted(
        (item for item in identities if item["partition"] == TRAIN_PARTITION and item["covers"]),
        key=by_rank,
    )
    validation_items = sorted(
        (item for item in identities if item["partition"] == VALIDATION_PARTITION and item["covers"]),
        key=by_rank,
    )
    holdout_items = sorted(
        (item for item in identities if item["partition"] in _HOLDOUT_PARTITIONS and item["covers"]),
        key=by_rank,
    )
    uncovered = sum(not item["covers"] for item in identities)
    tune_items = validation_items[:tune_limit]
    gradient_items = train_items + validation_items[tune_limit:]
    if not train_items or not tune_items or not gradient_items:
        raise SkillCenterTrainingError("train and validation envelopes are both required")
    if len(gradient_items) > streamed.MAX_SOURCES:
        raise SkillCenterTrainingError("gradient population exceeds the v2 source bound")
    gradient_ids = {str(item["source_digest"]) for item in gradient_items}
    tune_ids = [str(item["source_digest"]) for item in tune_items]
    holdout_ids = {str(item["source_digest"]) for item in holdout_items}
    if not set(tune_ids).isdisjoint(gradient_ids) or not holdout_ids.isdisjoint(gradient_ids | set(tune_ids)):
        raise SkillCenterTrainingError("tuning batch overlaps the gradient")
    gradient_partitions = sorted({str(item["partition"]) for item in gradient_items})
    print(
        f"v2_identities ready={len(identities)} gradient={len(gradient_items)} "
        f"tune={len(tune_items)} holdout={len(holdout_items)} not_ready={not_ready}",
        file=sys.stderr,
        flush=True,
    )
    columns, kept_verbs, vocabulary_summary = _fit_streamed_vocabulary(
        campaign_dir, gradient_items, projection_ids,
    )
    print(
        f"v2_vocabulary min_verb_documents={vocabulary_summary['threshold']} "
        f"kept_verbs={vocabulary_summary['kept_verb_count']} columns={len(columns)} "
        f"gradient_sources={len(gradient_items)}",
        file=sys.stderr,
        flush=True,
    )
    provisional = {
        "domain_id": "intent_ir",
        "projection_ids": projection_ids,
        "projections": descriptors,
        "columns": columns,
    }
    gradient_matrix, gradient_order, gradient_known, gradient_unknown, gradient_digest = _stream_feature_matrix(
        campaign_dir, gradient_items, provisional, kept_verbs, label="gradient", require_closed=True,
    )
    _tune_matrix, tune_order, tune_known, tune_unknown, tune_digest = _stream_feature_matrix(
        campaign_dir, tune_items, provisional, kept_verbs, label="tune", require_closed=False,
    )
    if tune_order != tune_ids:
        raise SkillCenterTrainingError("tuning batch order changed while streaming features")
    space = streamed.build_streamed_feature_space(
        domain="intent_ir",
        projection_ids=projection_ids,
        projections=descriptors,
        columns=columns,
        training_sources=sorted(gradient_ids),
        excluded_projection_ids=vocabulary_summary["excluded_projection_ids"],
        training_targets_sha256=gradient_digest,
    )
    if space["columns"] != columns or space["projections"] != descriptors:
        raise SkillCenterTrainingError("sealed feature space changed the fitted columns")
    if space["schema"] != "native-projection-feature-space/v2":
        raise SkillCenterTrainingError("streamed fit left the v1 feature space")
    record = {
        "schema": STREAMED_SPACE_RECORD_SCHEMA,
        "feature_space": space,
        "vocabulary_policy": STRUCTURAL_VIEW_V2_SCHEMA,
        "min_verb_documents": vocabulary_summary["threshold"],
        "kept_verbs": sorted(kept_verbs),
        "tuning_sources": tune_ids,
        "tuning_targets_sha256": tune_digest,
        "tuning_targets_sha256_method": streamed.TARGET_DIGEST_METHOD,
        "minibatch_size": minibatch_size,
        "verb_fit_population": "gradient_envelopes_only",
        "gradient_partitions": gradient_partitions,
        "holdout_partitions": list(_HOLDOUT_PARTITIONS),
    }
    record_path = campaign_dir / "v2_feature_space.json"
    if record_path.is_file():
        existing = json.loads(record_path.read_text(encoding="utf-8"))
        if streamed.digest(existing.get("feature_space")) != streamed.digest(space):
            raise SkillCenterTrainingError("v2 feature space file does not match the refit gradient vocabulary")
        if existing.get("kept_verbs") != record["kept_verbs"] or existing.get("tuning_sources") != tune_ids:
            raise SkillCenterTrainingError("v2 feature space file does not match the refit verbs")
        if existing.get("tuning_targets_sha256") != tune_digest or existing.get("minibatch_size") != minibatch_size:
            raise SkillCenterTrainingError("v2 feature space file does not match this training configuration")
    else:
        _write_json_durable(record_path, record)
    checkpoint_path = campaign_dir / "v2_checkpoint.json"
    resume: dict[str, Any] = {}
    if checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("schema") != streamed.CHECKPOINT_SCHEMA:
            raise SkillCenterTrainingError("v2 checkpoint schema is not recognized")
        if checkpoint.get("feature_space_sha256") != streamed.digest(space):
            raise SkillCenterTrainingError("v2 checkpoint belongs to a different feature space")
        expected_optimizer = {
            "epochs": epochs,
            "latent_width": latent_width,
            "learning_rate": learning_rate,
            "max_seconds": max_seconds,
            "seed": seed,
            "minibatch_size": minibatch_size,
        }
        if checkpoint.get("configuration") != expected_optimizer:
            raise SkillCenterTrainingError("v2 checkpoint belongs to a different optimizer configuration")
        for key in ("latest_state", "best_state", "best_objective", "best_metrics", "before", "epoch_reports"):
            if key not in checkpoint:
                raise SkillCenterTrainingError("v2 checkpoint is missing its training state")
        if not isinstance(checkpoint["epoch_reports"], list):
            raise SkillCenterTrainingError("v2 checkpoint epoch reports are unreadable")
        resume = {
            "base_state": checkpoint["latest_state"],
            "best_state": checkpoint["best_state"],
            "best_objective": checkpoint["best_objective"],
            "best_metrics": checkpoint["best_metrics"],
            "before": checkpoint["before"],
            "epoch_reports": checkpoint["epoch_reports"],
        }

    def persist_checkpoint(payload: Mapping[str, Any]) -> None:
        _write_json_durable(checkpoint_path, payload)
        latest_state = payload["latest_state"]
        print(
            f"v2_epoch epoch={latest_state['completed_epochs']} steps={latest_state['completed_steps']} "
            f"tune={float(payload['best_objective']):.6f} "
            f"selected_epochs={payload['best_state']['completed_epochs']} "
            f"stopped={payload['stopped_reason']}",
            file=sys.stderr,
            flush=True,
        )

    try:
        result = streamed.train_streamed_projection_features(
            space,
            gradient_matrix,
            gradient_order,
            _tune_matrix,
            tune_order,
            minibatch_size=minibatch_size,
            tuning_targets_sha256=tune_digest,
            epochs=epochs,
            latent_width=latent_width,
            learning_rate=learning_rate,
            max_seconds=max_seconds,
            seed=seed,
            checkpoint_callback=persist_checkpoint,
            **resume,
        )
    except streamed.ProjectionFeatureError as exc:
        raise SkillCenterTrainingError(str(exc)) from exc
    _assert_training_report(result["report"])
    holdout = _infer_v2_holdout(
        campaign_dir, holdout_items, space, result["state"], kept_verbs,
    )
    ready_covering = {str(item["source_digest"]) for item in identities if item["covers"]}
    full_ready_gradient = gradient_ids == ready_covering
    gradient_source_counts = {
        TRAIN_PARTITION: sum(item["partition"] == TRAIN_PARTITION for item in gradient_items),
        VALIDATION_PARTITION: sum(item["partition"] == VALIDATION_PARTITION for item in gradient_items),
    }
    holdout_source_counts = {
        name: sum(item["partition"] == name for item in holdout_items)
        for name in _HOLDOUT_PARTITIONS
    }
    _assert_campaign_files_unchanged(campaign_dir, untouched)
    if staging.exists() != staging_existed:
        raise SkillCenterTrainingError("v2 training changed candidate staging")
    report = result["report"]
    receipt = {
        "schema": STREAMED_TRAIN_SCHEMA,
        "dataset_repo_id": DATASET_REPO_ID,
        "dataset_revision": DATASET_REVISION,
        "upstream_dataset_id": UPSTREAM_DATASET_ID,
        "upstream_revision": UPSTREAM_REVISION,
        "split_digest": sha256_text((campaign_dir / split_name).read_text(encoding="utf-8")),
        "vocabulary_census_sha256": sha256_text(census_path.read_text(encoding="utf-8")),
        "vocabulary_policy": STRUCTURAL_VIEW_V2_SCHEMA,
        "verb_fit_population": "gradient_envelopes_only",
        "gradient_population": (
            "ready covering train rows and ready covering validation rows outside the ranked tune batch"
        ),
        "feature_space_schema": space["schema"],
        "state_schema": result["state"]["schema"],
        "feature_space_sha256": streamed.digest(space),
        "state_sha256": streamed.digest(result["state"]),
        "latest_state_sha256": streamed.digest(result["latest_state"]),
        "embedding_model_id": "native-projection-features",
        "embedding_revision": "v2",
        "min_verb_documents": vocabulary_summary["threshold"],
        "kept_verb_count": vocabulary_summary["kept_verb_count"],
        "unique_verb_count": vocabulary_summary["unique_verb_count"],
        "hapax_verb_count": vocabulary_summary["hapax_verb_count"],
        "view_column_count": len(space["columns"]),
        "projection_ids": projection_ids,
        "projection_column_counts": vocabulary_summary["projection_column_counts"],
        "excluded_projection_ids": space["excluded_projection_ids"],
        "threshold_curve": vocabulary_summary["curve"],
        "corpus_vocabulary_census_column_count": census.get("column_count"),
        "corpus_vocabulary_census_source_count": census.get("source_count"),
        "gradient_source_count": len(gradient_items),
        "gradient_source_counts": gradient_source_counts,
        "gradient_partitions": gradient_partitions,
        "tuning_source_count": len(tune_items),
        "tuning_sources": tune_ids,
        "tuning_partition": VALIDATION_PARTITION,
        "holdout_partitions": list(_HOLDOUT_PARTITIONS),
        "holdout_source_counts": holdout_source_counts,
        "holdout_ready_count": len(holdout_items),
        "holdout_inferred_count": holdout["inferred_count"],
        "holdout_no_feature_coverage_count": holdout["no_feature_coverage_count"],
        "holdout_known_atoms": holdout["known_atoms"],
        "holdout_unknown_atoms": holdout["unknown_atoms"],
        "holdout_rows_with_unknown_atoms": holdout["rows_with_unknown_atoms"],
        "holdout_no_feature_coverage_reasons": holdout["reasons"],
        "gradient_known_atoms": gradient_known,
        "gradient_unknown_atoms": gradient_unknown,
        "tuning_known_atoms": tune_known,
        "tuning_unknown_atoms": tune_unknown,
        "ready_row_count": len(identities),
        "not_ready_row_count": not_ready,
        "uncovered_projection_count": uncovered,
        "minibatch_size": minibatch_size,
        "source_bound": streamed.MAX_SOURCES,
        "feature_bound": features.MAX_FEATURES,
        "within_feature_bound": 1 <= len(space["columns"]) <= features.MAX_FEATURES,
        "within_source_bound": len(gradient_items) <= streamed.MAX_SOURCES,
        "configuration": configuration,
        "stopped_reason": report["stopped_reason"],
        "attempted_epochs": report["attempted_epochs"],
        "selected_total_epochs": report["selected_total_epochs"],
        "selected_completed_steps": report["selected_completed_steps"],
        "before_objective": report["before"]["objective"],
        "after_objective": report["after"]["objective"],
        "optimizer_elapsed_seconds": report["elapsed_seconds"],
        "elapsed_seconds": time.monotonic() - started,
        "full_corpus_gradient": False,
        "full_ready_gradient": full_ready_gradient,
        "training_executed": True,
        "registered": False,
        "decoded_formulas_generated": False,
        "tool_authority_granted": False,
        "qualified": False,
        "admitted": False,
        "formalized": False,
        "promotion_performed": False,
        "heldout_canary": False,
        "lake_executed": False,
        "weights_downloaded": False,
        "legal_encoder_transfer": "not_run",
        "qualification_gaps": [
            "source_meaning_not_verified",
            "backend_proofs_not_run",
            "tool_authority_not_granted",
        ],
    }
    _write_json_durable(receipt_path, receipt)
    _assert_campaign_files_unchanged(campaign_dir, untouched)
    if staging.exists() != staging_existed:
        raise SkillCenterTrainingError("v2 training changed candidate staging")
    return receipt


def _ready_feature_identities(
    campaign_dir: Path,
    index: Sequence[Mapping[str, Any]],
    projection_ids: Sequence[str],
    training_sources: set[str],
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    required = set(projection_ids)
    identities: list[dict[str, Any]] = []
    reservoir_counts: Counter[str] = Counter()
    full_counts: Counter[str] = Counter()
    seen: set[str] = set()
    ready_rows = 0
    for row in index:
        if not row.get("ready") or not row.get("source_digest"):
            continue
        envelope = _load_envelope(campaign_dir, str(row["source_digest"]))
        if envelope.digest != str(row["source_digest"]):
            raise SkillCenterTrainingError("envelope file digest does not match the target index")
        assert_envelope_authority(envelope.to_dict())
        source = envelope.source_digest
        if source in seen:
            raise SkillCenterTrainingError("duplicate source in ready envelopes")
        seen.add(source)
        payload = envelope.to_dict()
        names = {
            str(item["projection_id"])
            for item in payload["projections"]
            if item.get("logic_family") and item.get("expression")
        }
        covers = required <= names
        if source in training_sources and row["partition"] != TRAIN_PARTITION:
            raise SkillCenterTrainingError("reservoir source appears outside the train partition")
        identities.append(
            {
                "partition": str(row["partition"]),
                "file_digest": envelope.digest,
                "source_digest": source,
                "covers": covers,
            }
        )
        if covers:
            verbs = _verb_leaves(envelope)
            full_counts.update(verbs)
            if source in training_sources:
                reservoir_counts.update(verbs)
        ready_rows += 1
        if ready_rows % _INDEX_CHECKPOINT_EVERY == 0:
            _note_checkpoint("eligible_verbs", ready_rows)
    return identities, reservoir_counts, full_counts


def _structural_column_census(
    campaign_dir: Path,
    identities: Sequence[Mapping[str, Any]],
    projection_ids: Sequence[str],
    kept_verbs: frozenset[str],
) -> tuple[dict[str, int], int]:
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import _tokens

    observed: dict[str, set[str]] = {name: set() for name in projection_ids}
    selected = set(projection_ids)
    for ordinal, item in enumerate(identities, start=1):
        envelope = _load_envelope(campaign_dir, str(item["file_digest"]))
        for projection in envelope.to_dict()["projections"]:
            name = str(projection.get("projection_id") or "")
            expression = projection.get("expression")
            if name not in selected or not projection.get("logic_family") or not expression:
                continue
            tree = _structural_atom_tree(expression, kept_verbs=kept_verbs)
            observed[name].update(_tokens(tree))
        if ordinal % _INDEX_CHECKPOINT_EVERY == 0:
            _note_checkpoint("eligible_columns", ordinal)
            print(
                f"eligible_columns columns={sum(len(tokens) for tokens in observed.values())}",
                file=sys.stderr,
                flush=True,
            )
    counts = {name: len(observed[name]) for name in projection_ids}
    return counts, sum(counts.values())


def _infer_coverage_groups(
    campaign_dir: Path,
    features: Any,
    contract: Any,
    space: Mapping[str, Any],
    state: Mapping[str, Any],
    grouped: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    kept_verbs: frozenset[str],
) -> list[dict[str, Any]]:
    buckets = []
    projection_count = len(space["projection_ids"])
    for (partition, role), items in sorted(grouped.items()):
        bucket = {
            "partition": partition,
            "role": role,
            "ready_count": len(items),
            "inferred_count": 0,
            "no_feature_coverage_count": 0,
            "rows_with_unknown_atoms": 0,
            "known_atoms": 0,
            "unknown_atoms": 0,
            "reasons": Counter(),
        }
        if role == "gradient":
            buckets.append(bucket)
            continue
        for start in range(0, len(items), PILOT_SOURCE_LIMIT):
            batch = _load_envelopes(
                campaign_dir, [str(item["file_digest"]) for item in items[start : start + PILOT_SOURCE_LIMIT]],
            )
            inferred, failed = _infer_or_isolate(features, contract, space, state, batch, kept_verbs)
            for message in failed:
                bucket["no_feature_coverage_count"] += 1
                bucket["reasons"][message] += 1
            if inferred is None:
                continue
            if inferred.get("training_executed") is not False or inferred.get("decoded_formulas_generated") is not False:
                raise SkillCenterTrainingError("feature inference trained or emitted formulas")
            if any(inferred.get(flag) is not False for flag in (*_AUTHORITY, "promotion_performed")):
                raise SkillCenterTrainingError("feature inference claimed authority")
            coverage = list(inferred["coverage"])
            if projection_count == 0 or len(coverage) % projection_count != 0:
                raise SkillCenterTrainingError("feature inference coverage does not match the projections")
            bucket["inferred_count"] += len(inferred["rows"])
            for offset in range(0, len(coverage), projection_count):
                chunk = coverage[offset : offset + projection_count]
                bucket["known_atoms"] += sum(int(item["known_atoms"]) for item in chunk)
                bucket["unknown_atoms"] += sum(int(item["unknown_atoms"]) for item in chunk)
                if any(int(item["unknown_atoms"]) > 0 for item in chunk):
                    bucket["rows_with_unknown_atoms"] += 1
        buckets.append(bucket)
    return buckets


def _infer_or_isolate(
    features: Any,
    contract: Any,
    space: Mapping[str, Any],
    state: Mapping[str, Any],
    envelopes: Sequence[Any],
    kept_verbs: frozenset[str],
) -> tuple[Mapping[str, Any] | None, list[str]]:
    if not envelopes:
        return None, []
    viewed = structural_feature_envelopes(envelopes, kept_verbs=kept_verbs)
    try:
        return features.infer_projection_features(contract, space, state, viewed), []
    except features.ProjectionFeatureError as exc:
        if len(envelopes) == 1:
            return None, [str(exc).splitlines()[0][:240]]
        mid = len(envelopes) // 2
        left, left_failed = _infer_or_isolate(
            features, contract, space, state, envelopes[:mid], kept_verbs,
        )
        right, right_failed = _infer_or_isolate(
            features, contract, space, state, envelopes[mid:], kept_verbs,
        )
        if left is None:
            return right, left_failed + right_failed
        if right is None:
            return left, left_failed + right_failed
        merged = dict(left)
        merged["rows"] = list(left["rows"]) + list(right["rows"])
        merged["coverage"] = list(left["coverage"]) + list(right["coverage"])
        return merged, left_failed + right_failed


def _load_envelope(campaign_dir: Path, file_digest: str) -> Any:
    from ...formalization.autoencoder.domain_targets import DomainTargetEnvelope

    path = campaign_dir / "envelopes" / f"{file_digest}.json"
    if not path.is_file():
        raise SkillCenterTrainingError("ready envelope file is missing")
    return DomainTargetEnvelope(path.read_bytes())


def _load_envelopes(campaign_dir: Path, file_digests: Sequence[str]) -> list[Any]:
    return [_load_envelope(campaign_dir, digest) for digest in file_digests]


def _ranked_envelopes(envelopes: Sequence[Any], *, seed: str) -> list[Any]:
    return sorted(
        envelopes,
        key=lambda envelope: hashlib.sha256(
            f"{seed}\x1f{envelope.source_digest}".encode("utf-8")
        ).hexdigest(),
    )


def assert_envelope_authority(payload: Mapping[str, Any]) -> None:
    """Refuse an envelope that claims qualification before training starts."""

    if payload.get("domain_id") != "intent_ir":
        raise SkillCenterTrainingError("envelope domain is not intent_ir")
    if payload.get("ready_for_training") is not True:
        raise SkillCenterTrainingError("envelope is not ready for training")
    for name in _AUTHORITY:
        if payload.get(name) is not False:
            raise SkillCenterTrainingError(f"envelope {name} must stay false")


def _assert_pin(campaign_dir: Path) -> None:
    path = campaign_dir / "pin_receipt.json"
    if not path.is_file():
        raise SkillCenterTrainingError("pin receipt is missing")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("dataset_revision") != DATASET_REVISION:
        raise SkillCenterTrainingError("pin revision does not match the campaign constant")
    if receipt.get("dataset_repo_id") != DATASET_REPO_ID:
        raise SkillCenterTrainingError("pin repo is not Publicus/skillcenter-ir")


def _assert_training_report(report: Mapping[str, Any]) -> None:
    if report["after"]["objective"] > report["before"]["objective"]:
        raise SkillCenterTrainingError("tuning objective increased")
    for name, metrics in report["after"]["projections"].items():
        before = report["before"]["projections"][name]
        for key in ("reconstruction", "cosine"):
            if metrics[key] > before[key] + 1e-9:
                raise SkillCenterTrainingError(f"{name} {key} increased")
    for name in (
        "qualified",
        "admitted",
        "formalized",
        "promotion_performed",
        "heldout_canary",
        "lake_executed",
        "weights_downloaded",
    ):
        if report.get(name) is not False:
            raise SkillCenterTrainingError(f"training report {name} must stay false")


def _assert_disjoint_partitions(index: Sequence[Mapping[str, Any]]) -> None:
    seen: dict[str, str] = {}
    for row in index:
        if not row.get("ready") or not row.get("source_digest"):
            continue
        digest = str(row["source_digest"])
        previous = seen.get(digest)
        if previous is not None and previous != row["partition"]:
            raise SkillCenterTrainingError("one source digest is in two partitions")
        seen[digest] = str(row["partition"])


def _envelopes_covering(projection_ids: Sequence[str], envelopes: Sequence[Any]) -> list[Any]:
    required = set(projection_ids)
    covered = []
    for envelope in envelopes:
        names = {
            str(row["projection_id"])
            for row in envelope.to_dict()["projections"]
            if row.get("logic_family") and row.get("expression")
        }
        if required <= names:
            covered.append(envelope)
    return covered


def _common_family_projections(envelopes: Sequence[Any]) -> list[str]:
    sets: list[set[str]] = []
    for envelope in envelopes:
        names = {
            str(row["projection_id"])
            for row in envelope.to_dict()["projections"]
            if row.get("logic_family") and row.get("expression")
        }
        sets.append(names)
    if not sets:
        return []
    return sorted(set.intersection(*sets))


def _vocabulary_census(envelopes: Sequence[Any]) -> dict[str, Any]:
    from ....optimizers.logic_theorem_optimizer.autoencoder_projection_features import (
        MAX_FEATURES,
        ProjectionFeatureError,
        _tokens,
        build_feature_space,
    )

    projection_ids = _common_family_projections(envelopes)
    families: dict[str, str] = {}
    payloads: list[dict[str, Any]] = []
    digests: list[str] = []
    for envelope in envelopes:
        payload = envelope.to_dict()
        payloads.append(payload)
        digests.append(str(payload.get("source_digest") or ""))
        for row in payload["projections"]:
            if row.get("logic_family"):
                families[str(row["projection_id"])] = str(row["logic_family"])
    if len(digests) != len(set(digests)):
        raise SkillCenterTrainingError("duplicate source in feature batch")
    source_count = len(envelopes)
    column_counts: dict[str, int] = {}
    if projection_ids and payloads:
        observed: dict[str, set[str]] = {name: set() for name in projection_ids}
        descriptors: dict[str, dict[str, Any]] = {}
        descriptor_keys = (
            "logic_family",
            "profile",
            "properties",
            "view_role",
            "representation_kind",
            "producer_id",
        )
        for payload in payloads:
            present = {name: False for name in projection_ids}
            for projection in payload["projections"]:
                name = str(projection.get("projection_id") or "")
                if name not in observed:
                    continue
                descriptor = {key: projection.get(key) for key in descriptor_keys}
                if descriptor["logic_family"] is None:
                    raise SkillCenterTrainingError("projection roles cannot stand in for logic families")
                previous = descriptors.get(name)
                if previous is not None and previous != descriptor:
                    raise SkillCenterTrainingError("projection semantics changed between rows")
                descriptors[name] = descriptor
                expression = projection.get("expression")
                if not expression:
                    continue
                observed[name].update(_tokens(expression))
                present[name] = True
            if not all(present.values()):
                raise SkillCenterTrainingError("required projection absent or empty in a source row")
        column_counts = {name: len(observed[name]) for name in projection_ids}
    column_count = sum(column_counts.values())
    within_source_bound = source_count <= PILOT_SOURCE_LIMIT
    within_feature_bound = column_count <= MAX_FEATURES
    if projection_ids and envelopes and within_source_bound and within_feature_bound and column_count:
        try:
            space = build_feature_space("intent_ir", projection_ids, list(envelopes))
        except ProjectionFeatureError as exc:
            raise SkillCenterTrainingError(str(exc)) from exc
        if len(space["columns"]) != column_count or len(space["training_sources"]) != source_count:
            raise SkillCenterTrainingError("vocabulary census does not match the feature space")
    heaviest = [
        {"projection_id": name, "column_count": column_counts[name]}
        for name in sorted(column_counts, key=lambda name: (-column_counts[name], name))[:8]
    ]
    return {
        "projection_ids": projection_ids,
        "logic_families": {key: families[key] for key in projection_ids if key in families},
        "column_count": column_count,
        "projection_column_counts": column_counts,
        "heaviest_projections": heaviest,
        "within_feature_bound": within_feature_bound,
        "source_count": source_count,
        "within_source_bound": within_source_bound,
    }


def _pilot_draw(rows: Sequence[Mapping[str, Any]], *, seed: str, limit: int) -> list[Mapping[str, Any]]:
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get("repository_file") or row.get("primary_source_id") or row["entry_cid"])
        families[key].append(row)

    def rank(value: str) -> str:
        return hashlib.sha256(f"{seed}\x1f{value}".encode("utf-8")).hexdigest()

    ordered_families = sorted(families, key=rank)
    if len(ordered_families) > limit:
        return [
            sorted(families[family], key=lambda item: str(item["entry_cid"]))[0]
            for family in ordered_families[:limit]
        ]
    picked: list[Mapping[str, Any]] = []
    leftovers: list[Mapping[str, Any]] = []
    for family in ordered_families:
        members = sorted(families[family], key=lambda item: str(item["entry_cid"]))
        picked.append(members[0])
        leftovers.extend(members[1:])
    if len(picked) >= limit:
        return picked[:limit]
    leftovers.sort(key=lambda item: rank(str(item["entry_cid"])))
    return picked + leftovers[: limit - len(picked)]


def _smallest_holdout(counts: Counter[str]) -> tuple[str, ...]:
    populated = {key: value for key, value in counts.items() if key and value}
    if len(populated) < 2:
        return ()
    smallest = min(populated.values())
    candidates = sorted(key.casefold() for key, value in populated.items() if value == smallest)
    return (candidates[-1],)


def _target_index_row(capsule_row, partition, digest, ready, reason) -> dict[str, Any]:
    return {
        "entry_cid": capsule_row["entry_cid"],
        "document_id": capsule_row["document_id"],
        "document_sha256": capsule_row["document_sha256"],
        "partition": partition,
        "source_digest": digest,
        "ready": ready,
        "failure_reason": reason,
    }


def _public_target_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_cid": row["entry_cid"],
        "document_id": row["document_id"],
        "document_sha256": row["document_sha256"],
        "partition": row["partition"],
        "source_digest": row["source_digest"],
        "ready": bool(row["ready"]),
        "failure_reason": row["failure_reason"],
    }


def _reuse_target_progress(
    previous: Mapping[str, Any] | None,
    capsule_row: Mapping[str, Any],
    partition: str,
    envelope_dir: Path,
) -> dict[str, Any] | None:
    """Return a progress row when its envelope file still matches the capsule."""

    if not previous:
        return None
    if str(previous.get("document_sha256") or "") != str(capsule_row["document_sha256"]):
        return None
    if str(previous.get("entry_cid") or "") != str(capsule_row["entry_cid"]):
        return None
    digest = str(previous.get("source_digest") or "")
    if not digest or not (envelope_dir / f"{digest}.json").is_file():
        return None
    ready = bool(previous.get("ready"))
    detail = str(previous.get("failure_detail") or previous.get("failure_reason") or "")
    row = _target_index_row(
        capsule_row,
        partition,
        digest,
        ready,
        "" if ready else "not_ready",
    )
    row["failure_detail"] = "" if ready else (detail or "not_ready")
    return row


def _load_document(campaign_dir: Path, digest: str):
    from ..decoder import decode_intent_ir

    path = campaign_dir / "documents" / f"{digest}.json"
    return decode_intent_ir(json.loads(path.read_text(encoding="utf-8")))


def _load_partition_envelopes(campaign_dir: Path, index: Sequence[Mapping[str, Any]], partition: str):
    from ...formalization.autoencoder.domain_targets import DomainTargetEnvelope

    envelopes = []
    for row in index:
        if row["partition"] != partition or not row.get("ready"):
            continue
        raw = (campaign_dir / "envelopes" / f"{row['source_digest']}.json").read_bytes()
        envelopes.append(DomainTargetEnvelope(raw))
    return envelopes


def _ready_partition(campaign_dir: Path, index: Sequence[Mapping[str, Any]], partition: str):
    envelopes = _load_partition_envelopes(campaign_dir, index, partition)
    for envelope in envelopes:
        assert_envelope_authority(envelope.to_dict())
    return envelopes


def _disk_free(path: Path) -> int:
    probe = path if path.exists() else path.parent
    return int(os.statvfs(probe).f_bavail * os.statvfs(probe).f_frsize)


def _note_checkpoint(kind: str, rows: int) -> None:
    print(f"{kind} checkpoint rows={rows}", file=sys.stderr, flush=True)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        if not rows:
            pq.write_table(pa.table({}), temporary)
        else:
            pq.write_table(pa.Table.from_pylist([dict(row) for row in rows]), temporary)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    if not path.is_file() or path.stat().st_size == 0:
        return []
    table = pq.read_table(path)
    if table.num_columns == 0:
        return []
    return table.to_pylist()
