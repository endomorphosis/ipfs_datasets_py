#!/usr/bin/env python3
"""Seal and audit fail-closed LCR-084 exact-51 production evidence.

The committed LCR-023 cohort union remains inspectable but can never satisfy
``--require-live-official``. The production path is local-only: it reopens a
v2 exact-51 input map through ``run_state_laws_production_release.py``, replays
all normalized receipt/run-seal checks, verifies the completed local release
manifest and every descriptor, and binds those bytes to the LCR-084 candidate.
Production generation is local-only. Verification performs an authenticated
read-only Hub baseline observation plus a current-code replay whose explicit
provenance trust root is the verified retained acquisition bytes; it does not
claim to cryptographically reauthenticate the origin of those retained bytes.
No Hub mutation, upload, or publication operation is available here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from scripts.ops.legal_data import (
    build_state_laws_hf_release as candidate_builder,
)

TASK_ID: Final = "LCR-084"
GOAL_ID: Final = "LCR-G146"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "audit_state_laws_full_scrape_acceptance.py"
SCHEMA: Final = "ipfs_datasets_py/state-laws-full-scrape-acceptance@2"
ACCEPTANCE_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/full_scrape_acceptance.json")
CANDIDATE_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/release_candidate.json")
SCHEMA_RELPATH: Final = Path("data/legal/state_laws_full_scrape_acceptance.schema.json")
COHORT_F_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/cohort_f.json")
COHORT_I_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/cohort_i.json")
TWO_ROW_SYNTHETIC_MAX: Final = 2
MAX_EVIDENCE_AGE: Final = timedelta(days=30)
MAX_FUTURE_SKEW: Final = timedelta(0)
MAX_EVIDENCE_AGE_SECONDS: Final = int(MAX_EVIDENCE_AGE.total_seconds())

_NONAUTHORITATIVE_IDENTITY_RE: Final = re.compile(
    r"(?:fixture|synthetic|(?:^|[-_ ])sample(?:$|[-_ ])|static[-_ ]?transport|"
    r"gap[-_ ]?(?:refill|receipt)|cohort[-_ ]?[a-z0-9]*)",
    re.IGNORECASE,
)
_NONTERMINAL_STATUS = frozenset(
    {"building", "in_progress", "in-progress", "open", "partial", "pending", "running"}
)


class ScrapeAcceptanceError(RuntimeError):
    """Production evidence did not satisfy the exact LCR-084 contract."""


def _verifier_now() -> datetime:
    """Return the verifier-owned UTC time; callers cannot supply seal time."""

    return datetime.now(UTC)


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ScrapeAcceptanceError(f"JSON evidence contains duplicate key {key!r}")
        payload[key] = value
    return payload


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            candidate_builder.read_regular_file_bytes(
                path, label="required receipt"
            ).decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except ScrapeAcceptanceError:
        raise
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScrapeAcceptanceError(f"receipt is not strict JSON: {path.as_posix()}") from exc
    if type(payload) is not dict:
        raise ScrapeAcceptanceError(f"receipt root must be an object: {path.as_posix()}")
    return payload


def _load_snapshot(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    """Parse and hash the exact same no-follow byte snapshot."""

    try:
        payload, _, digest = candidate_builder.load_json_mapping_snapshot(
            path, label=label
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    return payload, digest


def _report_digest(payload: Mapping[str, Any]) -> str:
    return candidate_builder.digest_payload(
        {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    )


def _resolve_path(
    value: Any,
    *,
    repository_root: Path,
    label: str,
    directory: bool = False,
) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ScrapeAcceptanceError(f"{label} must be a non-empty path")
    selected = Path(value.strip()).expanduser()
    if not selected.is_absolute():
        selected = repository_root / selected
    for component in (selected, *selected.parents):
        if component.is_symlink():
            raise ScrapeAcceptanceError(f"{label} must not traverse a symlink: {component}")
    try:
        target = selected.resolve(strict=True)
    except OSError as exc:
        raise ScrapeAcceptanceError(f"{label} does not exist: {selected}") from exc
    valid = target.is_dir() if directory else target.is_file()
    if not valid:
        kind = "directory" if directory else "regular file"
        raise ScrapeAcceptanceError(f"{label} must be a {kind}: {target}")
    return target


def _resolve_release_relative(
    root: Path, value: Any, *, label: str
) -> Path:
    relative = str(value or "").strip()
    selected = Path(relative)
    if not relative or selected.is_absolute() or ".." in selected.parts:
        raise ScrapeAcceptanceError(f"{label} must be a confined relative path")
    lexical = candidate_builder._lexical_absolute(root / selected)
    cursor = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        cursor /= component
        if cursor.is_symlink():
            raise ScrapeAcceptanceError(f"{label} must not traverse a symlink: {cursor}")
    target = lexical.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ScrapeAcceptanceError(f"{label} escapes release output root") from exc
    if not target.is_file():
        raise ScrapeAcceptanceError(f"{label} is missing or unsafe: {target}")
    try:
        with candidate_builder._open_regular_file_nofollow(target, label=label):
            pass
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    return target


def _schema_validate(payload: Mapping[str, Any], *, repository_root: Path) -> None:
    schema = _load(repository_root / SCHEMA_RELPATH)
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(payload)),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    except ImportError as exc:
        raise ScrapeAcceptanceError(
            "jsonschema is required for LCR-084 production acceptance"
        ) from exc
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ScrapeAcceptanceError(
            f"acceptance schema validation failed at {location}: {first.message}"
        )


def _parse_utc(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ScrapeAcceptanceError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ScrapeAcceptanceError(f"{label} is not an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ScrapeAcceptanceError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _check_no_nonauthoritative_markers(receipt: Mapping[str, Any], *, jurisdiction: str) -> None:
    payload = receipt.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    for value in (
        receipt.get("receipt_id"), receipt.get("release_point"),
        receipt.get("source_software_version"), payload.get("producer"),
        payload.get("mode"), payload.get("transport_kind"),
        payload.get("evidence_kind"), payload.get("cohort"),
    ):
        if _NONAUTHORITATIVE_IDENTITY_RE.search(str(value or "")):
            raise ScrapeAcceptanceError(
                f"{jurisdiction} receipt contains fixture/sample/cohort/gap identity"
            )
    for key in (
        "fixture", "fixture_only", "sample", "sampled", "static_transport",
        "synthetic", "gap_refill",
    ):
        if payload.get(key) is True or receipt.get(key) is True:
            raise ScrapeAcceptanceError(
                f"{jurisdiction} receipt asserts prohibited {key} evidence"
            )


def _check_nonterminal_claims(value: Any, *, jurisdiction: str, path: str = "receipt") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            child = f"{path}.{raw_key}"
            if key in {"continuation", "continuation_token", "next_page", "next_token"} and item not in (None, "", [], {}):
                raise ScrapeAcceptanceError(f"{jurisdiction} has an open continuation at {child}")
            if key in {"all_attempts_terminal", "attempts_exhausted", "checkpoint_complete", "frontier_closed", "run_complete"} and item is False:
                raise ScrapeAcceptanceError(f"{jurisdiction} has nonterminal evidence at {child}")
            if key in {"partial", "partial_checkpoint", "open_frontier"} and item is True:
                raise ScrapeAcceptanceError(f"{jurisdiction} has partial/open evidence at {child}")
            if key == "status" and str(item or "").strip().lower() in _NONTERMINAL_STATUS:
                raise ScrapeAcceptanceError(f"{jurisdiction} has nonterminal status at {child}")
            _check_nonterminal_claims(item, jurisdiction=jurisdiction, path=child)
    elif isinstance(value, list):
        for position, item in enumerate(value):
            _check_nonterminal_claims(item, jurisdiction=jurisdiction, path=f"{path}[{position}]")


def _check_evidence_semantics(
    evidence: Mapping[str, Any], *, repository_root: Path, now: datetime
) -> None:
    jurisdictions = evidence.get("jurisdictions")
    if not isinstance(jurisdictions, list):
        raise ScrapeAcceptanceError("evidence.jurisdictions must be an array")
    codes = [str(item.get("jurisdiction") or "") for item in jurisdictions if isinstance(item, Mapping)]
    if codes != list(CANONICAL_JURISDICTION_ORDER) or len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise ScrapeAcceptanceError(
            "jurisdiction evidence must equal the canonical 50 states plus DC in order"
        )
    baseline = evidence.get("authenticated_live_baseline")
    reconciliation = evidence.get("baseline_reconciliation")
    official_replay = evidence.get("official_frontier_reobservation")
    source_bundle = evidence.get("source_bundle")
    union = evidence.get("union")
    release = evidence.get("production_release")
    if not isinstance(baseline, Mapping) or not isinstance(reconciliation, list):
        raise ScrapeAcceptanceError("authenticated baseline/reconciliation is missing")
    baseline_observed = _parse_utc(
        baseline.get("observed_at"), label="authenticated_live_baseline.observed_at"
    )
    if baseline_observed > now:
        raise ScrapeAcceptanceError("authenticated live baseline is in the future")
    # The stored LCR-081 receipt is the authenticated remote projection
    # anchor.  collect_production_evidence has just repeated the live Hub
    # observation and required exact projection equality, so the anchor uses
    # LCR-084's receipt window rather than expiring during its own bounded
    # exact-51 retained replay.
    if now - baseline_observed > MAX_EVIDENCE_AGE:
        raise ScrapeAcceptanceError("authenticated live baseline is stale")
    partitions = baseline.get("partitions")
    if not isinstance(partitions, list):
        raise ScrapeAcceptanceError("authenticated baseline partitions are missing")
    partition_codes = [
        str(item.get("jurisdiction") or "")
        for item in partitions
        if isinstance(item, Mapping)
    ]
    if partition_codes != list(CANONICAL_JURISDICTION_ORDER):
        raise ScrapeAcceptanceError("authenticated baseline is not canonical exact-51")
    if baseline.get("partitions_digest_sha256") != candidate_builder.digest_payload(partitions):
        raise ScrapeAcceptanceError("authenticated baseline partition digest drifted")
    source_identity_projection = [
        {
            "jurisdiction": item.get("jurisdiction"),
            "noncomparable_recovery_manifest_count": item.get(
                "noncomparable_recovery_manifest_count"
            ),
            "noncomparable_recovery_manifest_multiset_sha256": item.get(
                "noncomparable_recovery_manifest_multiset_sha256"
            ),
            "source_identity_count": item.get("source_identity_count"),
            "source_identity_multiset_sha256": item.get(
                "source_identity_multiset_sha256"
            ),
        }
        for item in partitions
        if isinstance(item, Mapping)
    ]
    if (
        baseline.get("source_identity_closure_schema")
        != candidate_builder.BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA
        or len(source_identity_projection) != EXPECTED_JURISDICTION_COUNT
        or baseline.get("source_identity_closure_digest_sha256")
        != candidate_builder.digest_payload(source_identity_projection)
    ):
        raise ScrapeAcceptanceError(
            "authenticated baseline source-identity closure drifted"
        )
    if (
        baseline.get("verifier_owned_live_reobservation") is not True
        or isinstance(baseline.get("live_replay_request_count"), bool)
        or int(baseline.get("live_replay_request_count", 0)) < 1
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(baseline.get("remote_projection_digest_sha256") or ""),
        )
        is None
    ):
        raise ScrapeAcceptanceError(
            "authenticated baseline lacks verifier-owned live Hub replay"
        )
    if not isinstance(official_replay, Mapping):
        raise ScrapeAcceptanceError(
            "verifier-owned official retained replay is missing"
        )
    official_rows = official_replay.get("jurisdictions")
    if not isinstance(official_rows, list):
        raise ScrapeAcceptanceError(
            "verifier-owned official retained replay has no jurisdictions"
        )
    official_codes = [
        str(item.get("jurisdiction") or "")
        for item in official_rows
        if isinstance(item, Mapping)
    ]
    if (
        official_replay.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT
        or official_codes != list(CANONICAL_JURISDICTION_ORDER)
        or official_replay.get("jurisdictions_digest_sha256")
        != candidate_builder.digest_payload(official_rows)
        or official_replay.get("network_io_performed") is not False
        or official_replay.get("verifier_owned") is not True
        or official_replay.get("derivation_reverified_with_current_code") is not True
        or official_replay.get("origin_reauthentication_performed") is not False
        or official_replay.get("provenance_trust_root")
        != "verified-retained-acquisition-bytes"
        or official_replay.get("retained_replay_completed") is not True
        or official_replay.get("copied_file_count") != 0
        or type(official_replay.get("hardlinked_file_count")) is not int
        or official_replay.get("hardlinked_file_count", 0) < 1
    ):
        raise ScrapeAcceptanceError(
            "verifier-owned official retained replay binding drifted"
        )
    if not isinstance(source_bundle, Mapping):
        raise ScrapeAcceptanceError("current source bundle binding is missing")
    source_versions = source_bundle.get("current_source_software_versions")
    if not isinstance(source_versions, list):
        raise ScrapeAcceptanceError("current source identities are missing")
    source_codes = [
        str(item.get("jurisdiction") or "")
        for item in source_versions
        if isinstance(item, Mapping)
    ]
    if (
        source_codes != list(CANONICAL_JURISDICTION_ORDER)
        or source_bundle.get("current_source_software_versions_digest_sha256")
        != candidate_builder.digest_payload(source_versions)
    ):
        raise ScrapeAcceptanceError("current source identity bundle is not exact-51")
    if not isinstance(union, Mapping) or not isinstance(release, Mapping):
        raise ScrapeAcceptanceError("production union/release evidence is missing")
    release_root = _resolve_path(
        release.get("output_root"),
        repository_root=repository_root,
        label="production output root",
        directory=True,
    )
    per_rows = union.get("per_jurisdiction")
    if not isinstance(per_rows, list):
        raise ScrapeAcceptanceError("production per-jurisdiction union is missing")
    per_codes = [
        str(item.get("jurisdiction") or "")
        for item in per_rows
        if isinstance(item, Mapping)
    ]
    reconciliation_codes = [
        str(item.get("jurisdiction") or "")
        for item in reconciliation
        if isinstance(item, Mapping)
    ]
    if per_codes != codes or reconciliation_codes != codes:
        raise ScrapeAcceptanceError("union/baseline rows are not canonical exact-51")
    rows_by_code = {
        str(item["jurisdiction"]): int(item["canonical_row_count"])
        for item in jurisdictions
    }
    baseline_by_code = {
        str(item["jurisdiction"]): item
        for item in partitions
        if isinstance(item, Mapping)
    }
    per_by_code = {
        str(item["jurisdiction"]): item
        for item in per_rows
        if isinstance(item, Mapping)
    }
    official_by_code = {
        str(item["jurisdiction"]): item
        for item in official_rows
        if isinstance(item, Mapping)
    }
    source_by_code = {
        str(item["jurisdiction"]): item
        for item in source_versions
        if isinstance(item, Mapping)
    }
    for per, comparison, jurisdiction in zip(per_rows, reconciliation, jurisdictions, strict=True):
        code = str(jurisdiction["jurisdiction"])
        acquired = rows_by_code[code]
        baseline_partition = baseline_by_code[code]
        baseline_rows = int(baseline_partition["num_rows"])
        baseline_identity_count = int(
            baseline_partition["source_identity_count"]
        )
        recovery_manifest_count = int(
            baseline_partition["noncomparable_recovery_manifest_count"]
        )
        delta = acquired - baseline_rows
        if not isinstance(comparison, Mapping):
            raise ScrapeAcceptanceError(
                f"{code} baseline reconciliation row is malformed"
            )
        added_count = int(comparison["added_source_identity_count"])
        expected_disposition = (
            "current_official_growth" if added_count > 0 else "exact_match"
        )
        empty_multiset_digest = candidate_builder.digest_payload([])
        if (
            baseline_identity_count + recovery_manifest_count != baseline_rows
            or comparison.get("jurisdiction") != code
            or comparison.get("acquired_row_count") != acquired
            or comparison.get("acquired_source_identity_count") != acquired
            or comparison.get("baseline_row_count") != baseline_rows
            or comparison.get("baseline_source_identity_count")
            != baseline_identity_count
            or comparison.get("baseline_source_identity_multiset_sha256")
            != baseline_partition.get("source_identity_multiset_sha256")
            or comparison.get(
                "baseline_noncomparable_recovery_manifest_count"
            )
            != recovery_manifest_count
            or comparison.get(
                "baseline_noncomparable_recovery_manifest_multiset_sha256"
            )
            != baseline_partition.get(
                "noncomparable_recovery_manifest_multiset_sha256"
            )
            or comparison.get(
                "baseline_noncomparable_recovery_manifest_disposition"
            )
            != "authenticated_baseline_recovery_manifest"
            or comparison.get("removed_source_identity_count") != 0
            or comparison.get("removed_source_identity_multiset_sha256")
            != empty_multiset_digest
            or acquired != baseline_identity_count + added_count
            or delta != added_count - recovery_manifest_count
            or comparison.get("delta_from_baseline") != delta
            or comparison.get("disposition") != expected_disposition
            or comparison.get("duplicate_count")
            != int(jurisdiction["duplicates"])
            or comparison.get("excluded_count")
            != int(jurisdiction["excluded"])
            or comparison.get("explained_delta_count")
            != recovery_manifest_count
            or comparison.get("quarantined_count")
            != int(jurisdiction["quarantined"])
            or (
                added_count == 0
                and comparison.get("added_source_identity_multiset_sha256")
                != empty_multiset_digest
            )
        ):
            raise ScrapeAcceptanceError(f"{code} baseline disposition arithmetic drifted")
        if not isinstance(per, Mapping):
            raise ScrapeAcceptanceError(f"{code} union closure row is malformed")
        dispositions = per.get("adapter_dispositions")
        if dispositions != {
            "admitted": acquired,
            "quarantined": 0,
            "rejected": 0,
        }:
            raise ScrapeAcceptanceError(f"{code} adapter dispositions drifted")
        if per.get("admitted_row_count") != acquired:
            raise ScrapeAcceptanceError(f"{code} union shard count drifted")
        official = official_by_code.get(code)
        source_identity = source_by_code.get(code)
        if not isinstance(official, Mapping) or not isinstance(
            source_identity, Mapping
        ):
            raise ScrapeAcceptanceError(f"{code} official replay binding is missing")
        selected = official.get("selected_evidence")
        runner = official.get("runner_identity_binding")
        if not isinstance(selected, Mapping) or not isinstance(runner, Mapping):
            raise ScrapeAcceptanceError(f"{code} official replay byte binding is missing")
        if (
            official.get("canonical_row_count") != acquired
            or official.get("official_source_url")
            != jurisdiction.get("official_source_url")
            or official.get("source_software_version")
            != jurisdiction.get("source_software_version")
            or source_identity.get("source_software_version")
            != jurisdiction.get("source_software_version")
            or runner.get("source_software_version")
            != jurisdiction.get("source_software_version")
            or runner.get("runner_start_identity")
            != source_bundle.get("refresh_runner_source_software_version")
            or runner.get("runner_end_identity")
            != source_bundle.get("refresh_runner_source_software_version")
            or selected.get("canonical_jsonld_sha256")
            != jurisdiction.get("canonical_jsonld_sha256")
            or selected.get("normalized_source_receipt_sha256")
            != jurisdiction.get("normalized_source_receipt_sha256")
            or selected.get("run_seal_canonical_jsonld_sha256")
            != jurisdiction.get("canonical_jsonld_sha256")
            or selected.get("run_seal_normalized_source_receipt_sha256")
            != jurisdiction.get("normalized_source_receipt_sha256")
            or selected.get("run_seal_sha256")
            != jurisdiction.get("run_seal_sha256")
            or selected.get("selected_corpus_rows_digest_sha256")
            != per.get("input_corpus_rows_digest_sha256")
            or selected.get("selected_entry_cids_digest_sha256")
            != per.get("input_entry_cids_digest_sha256")
            or official.get("corpus_entry_cids_digest_sha256")
            != per.get("input_entry_cids_digest_sha256")
        ):
            raise ScrapeAcceptanceError(
                f"{code} official replay/input/source binding drifted"
            )
        if (
            per.get("input_entry_cids_digest_sha256")
            != per.get("release_entry_cids_digest_sha256")
            or per.get("input_corpus_rows_digest_sha256")
            != per.get("release_corpus_rows_digest_sha256")
        ):
            raise ScrapeAcceptanceError(
                f"{code} input/release corpus row-key closure drifted"
            )
        shards = per.get("release_corpus_shards")
        if (
            not isinstance(shards, list)
            or not shards
            or per.get("release_corpus_shards_digest_sha256")
            != candidate_builder.digest_payload(shards)
            or sum(int(shard.get("row_count", -1)) for shard in shards) != acquired
        ):
            raise ScrapeAcceptanceError(f"{code} release corpus shard binding drifted")
    shard_sum = sum(rows_by_code.values())
    counts = release.get("counts")
    if not isinstance(counts, list):
        raise ScrapeAcceptanceError("production release counts are missing")
    count_map = {
        str(item.get("name")): int(item.get("value"))
        for item in counts
        if isinstance(item, Mapping)
    }
    deduped = int(count_map.get("corpus_documents", -1))
    key_parity = release.get("key_parity")
    if not isinstance(key_parity, Mapping):
        raise ScrapeAcceptanceError("production key parity is missing")
    source_receipts_digest = evidence.get("source_receipts_digest_sha256")
    if (
        shard_sum != deduped
        or union.get("shard_sum_before_dedup") != shard_sum
        or union.get("deduped_union_count") != deduped
        or union.get("duplicate_row_count") != 0
        or union.get("per_jurisdiction") != per_rows
        or union.get("input_source_receipts_digest_sha256")
        != source_receipts_digest
        or union.get("release_source_receipts_digest_sha256")
        != source_receipts_digest
        or union.get("deduped_union_count")
        != key_parity.get("parent_entry_cid_count")
        or union.get("deduped_entry_cids_digest_sha256")
        != key_parity.get("parent_entry_cids_sha256")
    ):
        raise ScrapeAcceptanceError("production deduped union arithmetic drifted")
    artifacts = release.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or release.get("artifact_count") != len(artifacts)
        or release.get("artifact_descriptors_digest_sha256")
        != candidate_builder.digest_payload(artifacts)
    ):
        raise ScrapeAcceptanceError("production artifact descriptor binding drifted")
    for item in jurisdictions:
        if not isinstance(item, Mapping):
            raise ScrapeAcceptanceError("jurisdiction evidence must contain only objects")
        code = str(item["jurisdiction"])
        observed = _parse_utc(item.get("observation_time"), label=f"{code}.observation_time")
        if observed > now + MAX_FUTURE_SKEW:
            raise ScrapeAcceptanceError(f"{code} observation_time is in the future")
        if now - observed > MAX_EVIDENCE_AGE:
            raise ScrapeAcceptanceError(
                f"{code} receipt is stale by more than {MAX_EVIDENCE_AGE.days} days"
            )
        run_sealed = _parse_utc(
            item.get("run_seal_created_at"), label=f"{code}.run_seal_created_at"
        )
        if run_sealed > now:
            raise ScrapeAcceptanceError(f"{code} run-final seal is in the future")
        if run_sealed < observed:
            raise ScrapeAcceptanceError(
                f"{code} run-final seal predates its official observation"
            )
        receipt_path = _resolve_path(
            item.get("normalized_source_receipt_path"), repository_root=repository_root,
            label=f"{code} normalized source receipt",
        )
        receipt, receipt_sha256 = _load_snapshot(
            receipt_path, label=f"{code} normalized source receipt"
        )
        if receipt_sha256 != item.get("normalized_source_receipt_sha256"):
            raise ScrapeAcceptanceError(f"{code} normalized source receipt hash drifted")
        release_receipt_path = _resolve_release_relative(
            release_root,
            item.get("release_source_receipt_path"),
            label=f"{code} embedded release source receipt",
        )
        release_receipt, release_receipt_sha256 = _load_snapshot(
            release_receipt_path,
            label=f"{code} embedded release source receipt",
        )
        if (
            release_receipt_sha256 != item.get("release_source_receipt_sha256")
            or candidate_builder.digest_payload(release_receipt)
            != item.get("release_source_receipt_digest_sha256")
            or release_receipt != receipt
        ):
            raise ScrapeAcceptanceError(
                f"{code} embedded output/input source receipt binding drifted"
            )
        closure = per_by_code.get(code)
        if not isinstance(closure, Mapping):
            raise ScrapeAcceptanceError(f"{code} release corpus closure is missing")
        for shard in closure.get("release_corpus_shards") or ():
            if not isinstance(shard, Mapping):
                raise ScrapeAcceptanceError(f"{code} release corpus shard is malformed")
            shard_path = _resolve_release_relative(
                release_root,
                shard.get("relative_path"),
                label=f"{code} release corpus shard",
            )
            if candidate_builder.file_sha256(shard_path) != shard.get("sha256"):
                raise ScrapeAcceptanceError(f"{code} release corpus shard hash drifted")
        canonical_path = _resolve_path(
            item.get("canonical_jsonld_path"), repository_root=repository_root,
            label=f"{code} canonical JSON-LD",
        )
        if candidate_builder.file_sha256(canonical_path) != item.get(
            "canonical_jsonld_sha256"
        ):
            raise ScrapeAcceptanceError(f"{code} canonical JSON-LD hash drifted")
        run_seal_path = _resolve_path(
            item.get("run_seal_path"), repository_root=repository_root,
            label=f"{code} run-final seal",
        )
        run_seal, run_seal_sha256 = _load_snapshot(
            run_seal_path, label=f"{code} run-final seal"
        )
        if run_seal_sha256 != item.get("run_seal_sha256"):
            raise ScrapeAcceptanceError(f"{code} run-final seal hash drifted")
        if run_seal.get("created_at") != item.get("run_seal_created_at"):
            raise ScrapeAcceptanceError(f"{code} run-final seal chronology drifted")
        _check_no_nonauthoritative_markers(receipt, jurisdiction=code)
        _check_nonterminal_claims(receipt, jurisdiction=code)
        hashes = receipt.get("content_hashes")
        if not isinstance(hashes, list) or not hashes:
            raise ScrapeAcceptanceError(f"{code} receipt lacks response/content hashes")
        if item.get("canonical_jsonld_sha256") not in hashes:
            raise ScrapeAcceptanceError(f"{code} receipt does not bind canonical JSON-LD hash")
        if item.get("content_hashes_digest_sha256") != candidate_builder.digest_payload(
            hashes
        ):
            raise ScrapeAcceptanceError(f"{code} content-hash set digest drifted")
        exact_receipt_fields = {
            "discovered": receipt.get("discovered"),
            "duplicates": receipt.get("duplicates", 0),
            "excluded": receipt.get("excluded"),
            "failed_final": receipt.get("failed_final"),
            "fetched": receipt.get("fetched"),
            "frontier_closed": receipt.get("frontier_closed"),
            "jurisdiction": receipt.get("jurisdiction"),
            "observation_time": receipt.get("observation_time"),
            "official_source_url": receipt.get("official_source_url"),
            "quarantined": receipt.get("quarantined"),
            "receipt_id": receipt.get("receipt_id"),
            "release_point": receipt.get("release_point"),
            "source_software_version": receipt.get("source_software_version"),
        }
        if any(item.get(key) != value for key, value in exact_receipt_fields.items()):
            raise ScrapeAcceptanceError(f"{code} normalized receipt projection drifted")


def _remeasure_report_evidence(payload: Mapping[str, Any], *, repository_root: Path) -> dict[str, Any]:
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ScrapeAcceptanceError("acceptance evidence is missing")
    input_map = evidence.get("input_map")
    rights = evidence.get("rights_receipt")
    release = evidence.get("production_release")
    source_control = evidence.get("source_control")
    baseline = evidence.get("authenticated_live_baseline")
    if not all(isinstance(item, Mapping) for item in (input_map, rights, release, source_control, baseline)):
        raise ScrapeAcceptanceError("acceptance evidence path bindings are malformed")
    input_map_path = _resolve_path(input_map.get("path"), repository_root=repository_root, label="input map")
    rights_path = _resolve_path(rights.get("path"), repository_root=repository_root, label="rights receipt")
    output_root = _resolve_path(
        release.get("output_root"), repository_root=repository_root,
        label="production output root", directory=True,
    )
    baseline_path = _resolve_path(
        baseline.get("path"), repository_root=repository_root,
        label="authenticated live baseline",
    )
    try:
        return candidate_builder.collect_production_evidence(
            input_map_path=input_map_path, rights_receipt_path=rights_path,
            production_output_root=output_root,
            live_baseline_path=baseline_path,
            source_revision=str(source_control.get("revision") or ""),
            repo_root=repository_root, require_clean_source=False,
            sealed_source_control=source_control,
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc


def _validate_candidate_binding(
    payload: Mapping[str, Any], *, acceptance_path: Path,
    acceptance_file_sha256: str, evidence: Mapping[str, Any], repository_root: Path,
) -> tuple[Path, dict[str, Any], str]:
    requirement = payload.get("candidate_requirement")
    if not isinstance(requirement, Mapping):
        raise ScrapeAcceptanceError("candidate_requirement is missing")
    expected_candidate_path = candidate_builder._lexical_absolute(
        repository_root / CANDIDATE_RELPATH
    )
    if candidate_builder._lexical_absolute(
        requirement.get("candidate_path"), base=repository_root
    ) != expected_candidate_path:
        raise ScrapeAcceptanceError(
            "candidate_requirement must bind the canonical production candidate"
        )
    candidate_path = _resolve_path(
        requirement.get("candidate_path"), repository_root=repository_root,
        label="production release candidate",
    )
    if candidate_path != expected_candidate_path:
        raise ScrapeAcceptanceError(
            "candidate_requirement must bind the canonical production candidate"
        )
    try:
        candidate, _, candidate_file_sha256 = (
            candidate_builder.load_json_mapping_snapshot(
                candidate_path, label="production release candidate"
            )
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    try:
        candidate_builder.check_production_candidate_report(
            candidate, repo_root=repository_root
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(f"production candidate is invalid: {exc}") from exc
    evidence_digest = candidate_builder.digest_payload(evidence)
    if requirement != {
        "candidate_path": candidate_builder._display_path(candidate_path, repo_root=repository_root),
        "candidate_schema": candidate_builder.PRODUCTION_REPORT_SCHEMA,
        "manifest_digest": evidence["production_release"]["manifest_digest"],
        "production_evidence_digest_sha256": evidence_digest,
    }:
        raise ScrapeAcceptanceError("candidate_requirement differs from exact evidence")
    if candidate.get("production_evidence") != dict(evidence):
        raise ScrapeAcceptanceError("candidate production evidence differs from acceptance")
    acceptance_binding = candidate.get("acceptance")
    if not isinstance(acceptance_binding, Mapping):
        raise ScrapeAcceptanceError("candidate acceptance binding is missing")
    if (
        acceptance_binding.get("full_scrape_acceptance_path")
        != candidate_builder._display_path(acceptance_path, repo_root=repository_root)
        or acceptance_binding.get("full_scrape_acceptance_sha256")
        != acceptance_file_sha256
        or acceptance_binding.get("full_scrape_acceptance_report_digest_sha256")
        != payload.get("report_digest_sha256")
        or acceptance_binding.get("full_scrape_acceptance_sealed_at")
        != payload.get("sealed_at")
        or candidate.get("sealed_at") != payload.get("sealed_at")
        or acceptance_binding.get("production_evidence_digest_sha256") != evidence_digest
    ):
        raise ScrapeAcceptanceError(
            "candidate does not bind exact acceptance bytes and production evidence"
        )
    try:
        candidate_bookend, _, candidate_bookend_sha256 = (
            candidate_builder.load_json_mapping_snapshot(
                candidate_path, label="production release candidate bookend"
            )
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    if (
        candidate_bookend_sha256 != candidate_file_sha256
        or candidate_bookend != candidate
    ):
        raise ScrapeAcceptanceError(
            "production release candidate changed during verification"
        )
    return candidate_path, candidate, candidate_file_sha256


def _two_row_jurisdictions(cohort: Mapping[str, Any]) -> list[str]:
    receipts = cohort.get("jurisdiction_receipts") or {}
    flagged: list[str] = []
    if not isinstance(receipts, Mapping):
        return flagged
    for code, body in receipts.items():
        if not isinstance(body, Mapping):
            continue
        row_count = int(body.get("row_count") or body.get("statutes_count") or 0)
        discovered = int((body.get("disposition") or {}).get("discovered") or 0)
        if row_count <= TWO_ROW_SYNTHETIC_MAX or discovered <= TWO_ROW_SYNTHETIC_MAX:
            flagged.append(str(code))
    return flagged


def _inspect_legacy(repository_root: Path) -> dict[str, Any]:
    acceptance = _load(repository_root / ACCEPTANCE_RELPATH)
    candidate = _load(repository_root / CANDIDATE_RELPATH)
    cohort_f = _load(repository_root / COHORT_F_RELPATH)
    cohort_i = _load(repository_root / COHORT_I_RELPATH)
    two_row = {"F": _two_row_jurisdictions(cohort_f), "I": _two_row_jurisdictions(cohort_i)}
    reasons: list[str] = []
    if two_row["F"] or two_row["I"]:
        reasons.append(
            "cohort F/I two-row reports cannot satisfy live official acceptance: "
            f"F={two_row['F']} I={two_row['I']}"
        )
    if acceptance.get("task_id") == "LCR-023":
        reasons.append("LCR-023 union receipt is untrusted synthetic success under LCR-084")
    if acceptance.get("producer") == "state_laws_acquisition_gap_refill.py":
        reasons.append("gap-refill producer cannot authorize live official production")
    if candidate.get("fixture_only") is True:
        reasons.append("fixture release candidate cannot satisfy production")
    return {
        "schema": SCHEMA, "producer": PRODUCER, "program_id": PROGRAM_ID,
        "task_id": TASK_ID, "goal_id": GOAL_ID, "mode": "inspect",
        "status": "blocked", "authorizing_for_publication": False,
        "authorizing_hub_upload": False, "reasons": reasons,
        "two_row_cohorts": two_row,
        "observed_jurisdiction_count": int(acceptance.get("observed_jurisdiction_count") or 0),
        "candidate_kind": str((candidate.get("candidate") or {}).get("kind") or ""),
    }


def seal_full_scrape_acceptance(
    *, input_map_path: Path | str, rights_receipt_path: Path | str,
    production_output_root: Path | str, source_revision: str,
    live_baseline_path: Path | str, candidate_path: Path | str,
    repository_root: Path = REPOSITORY_ROOT, require_clean_source: bool = True,
) -> dict[str, Any]:
    """Create (but do not write) one schema-valid local production receipt."""
    try:
        evidence = candidate_builder.collect_production_evidence(
            input_map_path=input_map_path, rights_receipt_path=rights_receipt_path,
            production_output_root=production_output_root,
            live_baseline_path=live_baseline_path,
            source_revision=source_revision, repo_root=repository_root,
            require_clean_source=require_clean_source,
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    now = _verifier_now()
    _check_evidence_semantics(evidence, repository_root=repository_root, now=now)
    evidence_digest = candidate_builder.digest_payload(evidence)
    try:
        candidate_target = candidate_builder._require_canonical_repo_path(
            candidate_path,
            repo_root=repository_root,
            relative_path=CANDIDATE_RELPATH,
            label="production release candidate",
            must_exist=False,
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    payload: dict[str, Any] = {
        "authorizing_for_publication": False, "authorizing_hub_upload": False,
        "candidate_requirement": {
            "candidate_path": candidate_builder._display_path(candidate_target, repo_root=repository_root),
            "candidate_schema": candidate_builder.PRODUCTION_REPORT_SCHEMA,
            "manifest_digest": evidence["production_release"]["manifest_digest"],
            "production_evidence_digest_sha256": evidence_digest,
        },
        "evidence": evidence, "freshness_max_age_seconds": MAX_EVIDENCE_AGE_SECONDS,
        "goal_id": GOAL_ID, "hub_mutation_performed": False,
        "jurisdiction_codes": list(CANONICAL_JURISDICTION_ORDER),
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT, "local_only": False,
        "mode": "live_official", "network_io_performed": True,
        "production_generation_local_only": True,
        "producer": PRODUCER, "production_evidence_digest_sha256": evidence_digest,
        "program_id": PROGRAM_ID, "report_digest_sha256": "0" * 64,
        "read_only_live_verification": True,
        "schema": SCHEMA, "sealed_at": now.isoformat().replace("+00:00", "Z"),
        "status": "passed", "task_id": TASK_ID,
    }
    payload["report_digest_sha256"] = _report_digest(payload)
    _schema_validate(payload, repository_root=repository_root)
    return payload


def inspect_full_scrape_acceptance(
    *, require_live_official: bool, require_jurisdictions: int,
    require_production_candidate: bool, repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    if not require_live_official and not require_production_candidate:
        return _inspect_legacy(repository_root)
    if require_jurisdictions != EXPECTED_JURISDICTION_COUNT:
        raise ScrapeAcceptanceError(
            "production acceptance requires exact equality to canonical 51 jurisdictions"
        )
    acceptance_path = repository_root / ACCEPTANCE_RELPATH
    payload, acceptance_file_sha256 = _load_snapshot(
        acceptance_path, label="required receipt"
    )
    if payload.get("task_id") == "LCR-023" or payload.get("producer") == (
        "state_laws_acquisition_gap_refill.py"
    ):
        raise ScrapeAcceptanceError(
            "synthetic LCR-023/gap-refill acceptance cannot satisfy live official production"
        )
    _schema_validate(payload, repository_root=repository_root)
    if payload.get("report_digest_sha256") != _report_digest(payload):
        raise ScrapeAcceptanceError("acceptance report digest does not match payload")
    if payload.get("jurisdiction_codes") != list(CANONICAL_JURISDICTION_ORDER):
        raise ScrapeAcceptanceError("acceptance jurisdictions are not canonical exact-51")
    if payload.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT:
        raise ScrapeAcceptanceError("acceptance jurisdiction_count is not exactly 51")
    if payload.get("freshness_max_age_seconds") != MAX_EVIDENCE_AGE_SECONDS:
        raise ScrapeAcceptanceError("acceptance freshness policy drifted")
    measured = _remeasure_report_evidence(payload, repository_root=repository_root)
    if payload.get("evidence") != measured:
        raise ScrapeAcceptanceError("acceptance evidence differs from current verified bytes")
    evidence_digest = candidate_builder.digest_payload(measured)
    if payload.get("production_evidence_digest_sha256") != evidence_digest:
        raise ScrapeAcceptanceError("acceptance production evidence digest drifted")
    checked_at = _verifier_now()
    sealed_at = _parse_utc(payload.get("sealed_at"), label="sealed_at")
    if sealed_at > checked_at:
        raise ScrapeAcceptanceError("acceptance sealed_at is in the future")
    chronology = [
        _parse_utc(item.get("observation_time"), label="jurisdiction observation_time")
        for item in measured["jurisdictions"]
    ] + [
        _parse_utc(item.get("run_seal_created_at"), label="run_seal_created_at")
        for item in measured["jurisdictions"]
    ] + [
        _parse_utc(
            measured["authenticated_live_baseline"].get("observed_at"),
            label="authenticated_live_baseline.observed_at",
        )
    ]
    if any(item > sealed_at for item in chronology):
        raise ScrapeAcceptanceError("acceptance sealed_at predates bound evidence")
    _check_evidence_semantics(measured, repository_root=repository_root, now=checked_at)
    candidate_path, candidate, candidate_file_sha256 = _validate_candidate_binding(
        payload,
        acceptance_path=acceptance_path,
        acceptance_file_sha256=acceptance_file_sha256,
        evidence=measured,
        repository_root=repository_root,
    )
    acceptance_bookend, acceptance_bookend_sha256 = _load_snapshot(
        acceptance_path, label="required receipt bookend"
    )
    if (
        acceptance_bookend_sha256 != acceptance_file_sha256
        or acceptance_bookend != payload
    ):
        raise ScrapeAcceptanceError(
            "production acceptance report changed during verification"
        )
    try:
        candidate_bookend, _, candidate_bookend_sha256 = (
            candidate_builder.load_json_mapping_snapshot(
                candidate_path, label="production release candidate final bookend"
            )
        )
    except candidate_builder.CandidateError as exc:
        raise ScrapeAcceptanceError(str(exc)) from exc
    if (
        candidate_bookend_sha256 != candidate_file_sha256
        or candidate_bookend != candidate
    ):
        raise ScrapeAcceptanceError(
            "production release candidate changed during verification"
        )
    return {
        **dict(payload),
        "candidate_file_sha256": candidate_file_sha256,
        "candidate_report_digest_sha256": candidate["report_digest_sha256"],
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed LCR-084 exact-51 production acceptance"
    )
    parser.add_argument("--require-live-official", action="store_true")
    parser.add_argument("--require-jurisdictions", type=int, default=51)
    parser.add_argument("--require-production-candidate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--input-map", type=Path, default=None)
    parser.add_argument("--rights-receipt", type=Path, default=None)
    parser.add_argument("--production-output-root", type=Path, default=None)
    parser.add_argument("--live-baseline", type=Path, default=None)
    parser.add_argument("--source-revision", default="")
    parser.add_argument("--candidate", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.check == args.write:
        sys.stderr.write(
            "audit_state_laws_full_scrape_acceptance: FAILED: choose exactly one of --check/--write\n"
        )
        return 2
    report_path = candidate_builder._lexical_absolute(
        args.report if args.report is not None else REPOSITORY_ROOT / ACCEPTANCE_RELPATH
    )
    try:
        if args.write:
            required = {
                "--input-map": args.input_map, "--rights-receipt": args.rights_receipt,
                "--production-output-root": args.production_output_root,
                "--live-baseline": args.live_baseline,
                "--source-revision": args.source_revision,
            }
            missing = [name for name, value in required.items() if value in (None, "")]
            if missing:
                raise ScrapeAcceptanceError(f"write requires production evidence: {missing}")
            expected_report = candidate_builder._lexical_absolute(
                REPOSITORY_ROOT / ACCEPTANCE_RELPATH
            )
            if report_path != expected_report:
                raise ScrapeAcceptanceError("--write requires canonical acceptance report path")
            try:
                candidate_builder._require_canonical_repo_path(
                    report_path,
                    repo_root=REPOSITORY_ROOT,
                    relative_path=ACCEPTANCE_RELPATH,
                    label="production acceptance report",
                    must_exist=False,
                )
            except candidate_builder.CandidateError as exc:
                raise ScrapeAcceptanceError(str(exc)) from exc
            candidate_path = candidate_builder._lexical_absolute(
                args.candidate
                if args.candidate is not None
                else REPOSITORY_ROOT / CANDIDATE_RELPATH
            )
            report = seal_full_scrape_acceptance(
                input_map_path=args.input_map, rights_receipt_path=args.rights_receipt,
                production_output_root=args.production_output_root,
                live_baseline_path=args.live_baseline,
                source_revision=args.source_revision, candidate_path=candidate_path,
                repository_root=REPOSITORY_ROOT,
            )
            candidate_builder.write_json_report(report, report_path)
        else:
            if args.report is not None and report_path != candidate_builder._lexical_absolute(
                REPOSITORY_ROOT / ACCEPTANCE_RELPATH
            ):
                raise ScrapeAcceptanceError("--check requires canonical acceptance report path")
            report = inspect_full_scrape_acceptance(
                require_live_official=bool(args.require_live_official),
                require_jurisdictions=int(args.require_jurisdictions),
                require_production_candidate=bool(args.require_production_candidate),
                repository_root=REPOSITORY_ROOT,
            )
    except ScrapeAcceptanceError as exc:
        sys.stderr.write(f"audit_state_laws_full_scrape_acceptance: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "audit_state_laws_full_scrape_acceptance: "
            f"{str(report['status']).upper()} mode={report['mode']}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
