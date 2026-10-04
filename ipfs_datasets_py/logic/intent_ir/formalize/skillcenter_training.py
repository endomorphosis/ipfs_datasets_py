"""Pinned, local SkillCenter sources for experimental Intent feature training.

The public retrieval corpus has no reviewed instruction-to-logic targets.  This
adapter preserves that distinction: native normalizer targets are weak,
source-grounded declarations, and source content never becomes instructions.
It performs no downloads, source execution, model calls, or publication.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import fields
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

SCHEMA = "skillcenter-intent-feature-corpus/v1"
DESCRIPTOR_SCHEMA = "skillcenter-intent-feature-corpus-descriptor/v1"
REPOSITORY = "Publicus/skillcenter-ir"
MAX_BYTES = 32 * 1024 * 1024


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_wire(value))


def _hash(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("an exact lowercase SHA-256 digest is required")
    return value


def _file(root: Path, relative: str, *, digest: str, size: int | None = None) -> bytes:
    pure = PurePosixPath(relative)
    if (not relative or pure.is_absolute() or pure.as_posix() != relative
            or any(p in {".", ".."} for p in pure.parts)):
        raise ValueError("release files must have canonical relative paths")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("release files must stay inside the pinned root")
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("release file missing or above the 32 MiB bound")
    raw = path.read_bytes()
    if _sha(raw) != _hash(digest) or (size is not None and len(raw) != size):
        raise ValueError("pinned release file hash or size mismatch")
    return raw


def _record(row: Mapping[str, Any]):
    from ..source_adapters.skillcenter import SkillCenterSkillRecord

    values = {}
    for field in fields(SkillCenterSkillRecord):
        value = row[field.name]
        if field.name != "overall_score" and (not isinstance(value, str) or len(value) > 1_000_000):
            raise ValueError("SkillCenter records require bounded typed text")
        values[field.name] = value
    record = SkillCenterSkillRecord(**values)
    if (record.content_sha256 != row["content_sha256"]
            or record.content_cid != row["content_cid"]
            or record.entry_cid != row["entry_cid"]
            or record.entry_identity.sha256 != row["entry_sha256"]):
        raise ValueError("SkillCenter content or entry identity mismatch")
    return record


def _repository_group(url: str) -> str:
    """Group registry versions by package, Git sources by owning repository."""
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    parts = [p for p in parsed.path.split("/") if p]
    if host in {"clawhub.ai", "www.clawhub.ai"} and len(parts) >= 2 and parts[0] == "registry":
        return host + "/registry/" + parts[1]
    if host in {"github.com", "www.github.com", "gitlab.com", "www.gitlab.com"} and len(parts) >= 2:
        return host + "/" + "/".join(parts[:2]).casefold()
    # An unknown source keeps the native conservative host-level fence.
    return host or url


def _producer_pins() -> dict[str, str]:
    from ..normalize import skill
    from ..source_adapters import policy, skillcenter
    from ..evaluation import splits
    from ...formalization.autoencoder import domain_targets
    from . import compiler
    modules = (skill, policy, skillcenter, splits, domain_targets, compiler)
    return {m.__name__: _sha(Path(m.__file__).read_bytes()) for m in modules}


def _assemble(*, release_root: Path, release_revision: str,
              expected_manifest_sha256: str, shards: Sequence[str],
              max_examples: int) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ..evaluation.splits import IntentSplitConfig, build_intent_splits
    from ..normalize.skill import SkillCenterIntentNormalizer
    from ..source_adapters.policy import AllowedUseDecision, SkillSourcePolicy
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets

    if not isinstance(release_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", release_revision):
        raise ValueError("an immutable 40-character Hub revision is required")
    if type(max_examples) is not int or not 1 <= max_examples <= 512:
        raise ValueError("max_examples must be between 1 and 512")
    if isinstance(shards, (str, bytes)) or not 1 <= len(shards) <= 8 or len(set(shards)) != len(shards):
        raise ValueError("one to eight distinct corpus shard paths are required")
    root = Path(release_root).resolve()
    raw = _file(root, "manifest.json", digest=expected_manifest_sha256)
    manifest = json.loads(raw)
    if (manifest.get("schema_version") != "skillcenter-huggingface-release/v3"
            or manifest.get("dataset_repo_id") != REPOSITORY):
        raise ValueError("expected the Publicus SkillCenter v3 release")
    index_pin = manifest["indexes"]["corpus_chunks"]
    index_raw = _file(root, index_pin["relative_path"], digest=index_pin["sha256"], size=index_pin["size_bytes"])
    index = {r["relative_path"]: r for r in pq.read_table(pa.BufferReader(index_raw)).to_pylist()}
    rows, pins = [], []
    bytes_read = len(raw) + len(index_raw)
    for name in sorted(shards):
        if name not in index or not name.startswith("data/corpus/"):
            raise ValueError("requested shard is not in the pinned corpus index")
        pin = index[name]
        if type(pin["size_bytes"]) is not int or bytes_read + pin["size_bytes"] > MAX_BYTES:
            raise ValueError("selected corpus inputs exceed the 32 MiB bound")
        shard_raw = _file(root, name, digest=pin["sha256"], size=pin["size_bytes"])
        table = pq.read_table(pa.BufferReader(shard_raw))
        if table.num_rows != pin["row_count"] or table.num_rows > 4096:
            raise ValueError("corpus shard row count differs from its index")
        if (table.schema.metadata or {}).get(b"schema_version") != b"skillcenter-corpus-row/v1":
            raise ValueError("unsupported corpus row schema")
        rows.extend(table.to_pylist())
        pins.append({"path": name, "sha256": pin["sha256"], "size_bytes": len(shard_raw), "rows": table.num_rows})
        bytes_read += len(shard_raw)
    counts = Counter(scanned_rows=len(rows))
    eligible, excluded = [], []
    policy, normalizer = SkillSourcePolicy(), SkillCenterIntentNormalizer()
    seen = set()
    for row in rows:
        record = _record(row)
        if (record.dataset_id != manifest["dataset_id"]
                or record.dataset_revision != manifest["dataset_revision"]):
            raise ValueError("corpus row upstream provenance differs from the release")
        if record.entry_cid in seen:
            raise ValueError("duplicate entry CID across selected corpus shards")
        seen.add(record.entry_cid)
        if row["license_risk"] != "allow":
            counts["release_license_review_rows"] += 1
            continue
        counts["release_license_allow_rows"] += 1
        decision = policy.evaluate(record)
        if decision.allowed_use != AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH:
            counts["native_policy_excluded_rows"] += 1
            excluded.append({"entry_cid": record.entry_cid, "content_sha256": record.content_sha256,
                             "reason": "native_source_policy", "allowed_use": decision.allowed_use.value})
            continue
        counts["source_eligible_rows"] += 1
        eligible.append((row, record))
    split_inputs = [{"sample_id": r.entry_cid, "domain": r.domain,
                     "primary_source_id": r.primary_source_id, "content_sha256": r.content_sha256,
                     "source_id": r.source_id, "source_url": r.source_url,
                     "repository_ids": [_repository_group(r.source_url)],
                     "dataset_revision": r.dataset_revision, "skill_md": r.skill_md}
                    for _, r in eligible]
    split_manifest = build_intent_splits(split_inputs, IntentSplitConfig(seed="skillcenter-intent-feature-development-v1"))
    samples = []
    for row, record in sorted(eligible, key=lambda pair: pair[1].entry_cid)[:max_examples]:
        normalized = normalizer.normalize_with_diagnostics(record)
        targets = prepare_intent_targets(normalized.document)
        samples.append({"id": record.entry_cid, "split": split_manifest.assignments[record.entry_cid],
                        "instruction": record.skill_md, "source_sha256": record.content_sha256,
                        "source_record": {f.name: getattr(record, f.name) for f in fields(record)},
                        "source_identity": {k: row[k] for k in ("content_cid", "entry_sha256", "entry_cid", "content_sha256")},
                        "license_expression": row["license_expression"], "domain": record.domain,
                        "native_policy": normalized.policy_decision.to_dict(),
                        "native_weak_targets": targets.to_dict(),
                        "normalizer_diagnostics": [d.to_dict() for d in normalized.diagnostics]})
    counts.update(selected_rows=len(samples), fully_ready_native_targets=sum(s["native_weak_targets"]["ready_for_training"] for s in samples))
    return {"schema": SCHEMA, "dataset_repo_id": REPOSITORY, "release_revision": release_revision,
            "release_root": str(root), "release_manifest_sha256": expected_manifest_sha256,
            "upstream_dataset_id": manifest["dataset_id"], "upstream_dataset_revision": manifest["dataset_revision"],
            "shards": pins, "input_bytes": bytes_read, "max_examples": max_examples,
            "producer_sha256": _producer_pins(), "split_manifest": split_manifest.to_dict(),
            "samples": samples, "excluded": excluded, "counts": dict(counts),
            "selected_split_counts": dict(Counter(s["split"] for s in samples)),
            "supervision": "native_structural_weak_targets_not_reviewed_instruction_to_logic_pairs",
            "split_scope": "locally_assigned_development_partitions_of_public_train_shards",
            "holdout_status": "development_only_not_an_independent_semantic_generalization_test",
            "source_content_executed": False, "provider_calls": 0, "gold_formal_target_count": 0,
            "qualified": False, "admitted": False}


def export_skillcenter_training_corpus(*, release_root: Path, release_revision: str,
        expected_manifest_sha256: str, shards: Sequence[str], output: Path,
        max_examples: int = 32) -> dict[str, Any]:
    """Replay a pinned local release and create a new, bounded source export."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("a fresh output directory is required")
    report = _assemble(release_root=release_root, release_revision=release_revision,
                       expected_manifest_sha256=expected_manifest_sha256, shards=shards, max_examples=max_examples)
    raw = _wire(report)
    if len(raw) > MAX_BYTES:
        raise ValueError("export exceeds the 32 MiB bound")
    output.mkdir(parents=True)
    path = output / "corpus.json"
    path.write_bytes(raw)
    return {"schema": DESCRIPTOR_SCHEMA, "path": str(path), "sha256": _sha(raw)}


def load_skillcenter_training_corpus(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute identities, policy, target producers, and source-family splits."""
    if set(descriptor) != {"schema", "path", "sha256"} or descriptor["schema"] != DESCRIPTOR_SCHEMA:
        raise ValueError("exact corpus descriptor required")
    path = Path(descriptor["path"])
    if not path.is_absolute():
        raise ValueError("absolute corpus path required")
    raw = _file(path.parent, path.name, digest=descriptor["sha256"])
    report = json.loads(raw)
    expected = _assemble(release_root=Path(report["release_root"]), release_revision=report["release_revision"],
                         expected_manifest_sha256=report["release_manifest_sha256"],
                         shards=[p["path"] for p in report["shards"]], max_examples=report["max_examples"])
    if _wire(report) != _wire(expected):
        raise ValueError("corpus evidence differs from the pinned native replay")
    return report
