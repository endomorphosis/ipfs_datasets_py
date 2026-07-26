from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from ipfs_datasets_py.logic.intent_ir.source_adapters.pilot import (
    GITHUB_ALL_FILENAME,
    PilotBounds,
    PilotBundleSpec,
    PilotExpansionPolicy,
    PilotRunMode,
    ROLLOUT_GATE_NAMES,
    SkillCenterPilot,
    SkillCenterPilotGateError,
    SkillCenterPilotManifest,
    SkillCenterPilotManifestError,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshotCache,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


FIXTURE_MANIFEST = (
    Path(__file__).parents[3]
    / "fixtures"
    / "intent_ir"
    / "skillcenter"
    / "manifest.json"
)
REVISION = "f9dd4fec3c86d85ebf116c7408ac5ce602c418a1"


class RecordingStore:
    def __init__(self) -> None:
        self.blocks: dict[str, tuple[bytes, str]] = {}

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        address = cid_v1(payload)
        self.blocks[address] = (payload, media_type)
        return address


def _write_bundle(path: Path, *, profile: str, version: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE bundle_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE skills_index (
            skill_id TEXT PRIMARY KEY,
            domain TEXT,
            profile TEXT,
            source_type TEXT,
            source_url TEXT,
            title TEXT,
            overall_score REAL,
            skill_kind TEXT,
            language TEXT,
            source_id TEXT,
            primary_source_id TEXT
        );
        CREATE TABLE skills_content (
            skill_id TEXT PRIMARY KEY,
            metadata_yaml TEXT,
            skill_md TEXT,
            library_md TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO bundle_meta(key, value) VALUES (?, ?)",
        (
            ("bundle_type", "lite"),
            ("created_at", "2026-07-24T00:00:00Z"),
            ("total_skills", "2"),
            ("version", version),
        ),
    )
    index_rows = (
        (
            f"{profile}-a-allowed",
            "security" if profile == "security-lite" else "agent-skills",
            profile,
            "github",
            f"https://example.test/{profile}/allowed",
            f"{profile} bounded report",
            5.0,
            "github",
            "en",
            f"{profile}-source-a",
            f"{profile}-primary-a",
        ),
        (
            f"{profile}-z-blocked",
            "security" if profile == "security-lite" else "agent-skills",
            profile,
            "repo",
            f"https://example.test/{profile}/blocked",
            f"{profile} blocked record",
            1.0,
            "community",
            "en",
            f"{profile}-source-z",
            f"{profile}-primary-z",
        ),
    )
    connection.executemany(
        "INSERT INTO skills_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        index_rows,
    )
    allowed_body = (
        "# Bounded report\n\n"
        "## Goal\n"
        "- Produce a bounded report.\n\n"
        "## Steps\n"
        "1. Read the input.\n"
        "2. Write the report.\n\n"
        "## Verification\n"
        "- Confirm the report exists.\n"
    )
    connection.executemany(
        "INSERT INTO skills_content VALUES (?, ?, ?, ?)",
        (
            (
                f"{profile}-a-allowed",
                'license_spdx: "MIT"\nlicense_risk: "allow"\n',
                allowed_body,
                "",
            ),
            (
                f"{profile}-z-blocked",
                "license: Complete terms in LICENSE.txt\n",
                "# Unreviewed source\n\nThis record has unknown license terms.\n",
                "",
            ),
        ),
    )
    connection.commit()
    connection.close()


def _synthetic_manifest(paths: Mapping[str, Path]) -> SkillCenterPilotManifest:
    bundles = []
    for profile, version in (
        ("security-lite", "fixture-security-v1"),
        ("github-lite", "fixture-github-v1"),
    ):
        path = paths[profile]
        bundles.append(
            PilotBundleSpec(
                profile=profile,
                repository_file=path.name,
                expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                expected_size_bytes=path.stat().st_size,
                expected_total_skills=2,
                expected_bundle_type="lite",
                expected_bundle_version=version,
                sample_limit=1,
            )
        )
    filenames = tuple(item.repository_file for item in bundles)
    return SkillCenterPilotManifest(
        dataset_id="example/skillcenter-pilot",
        dataset_revision=REVISION,
        bundles=tuple(bundles),
        bounds=PilotBounds(
            max_bundle_count=2,
            max_total_records=4,
            max_text_chars=10_000,
            batch_size=1,
            max_elapsed_seconds=30,
            max_peak_memory_bytes=2_147_483_648,
        ),
        expansion_policy=PilotExpansionPolicy(
            allowed_repository_files=filenames,
            prohibited_repository_files=(GITHUB_ALL_FILENAME,),
            github_all_requires_rollout_gates=ROLLOUT_GATE_NAMES,
        ),
    )


@pytest.fixture
def offline_pilot(
    tmp_path: Path,
) -> tuple[SkillCenterPilot, SkillCenterPilotManifest]:
    sources = tmp_path / "source"
    sources.mkdir()
    paths = {
        "security-lite": sources / "security-lite.sqlite",
        "github-lite": sources / "github-lite.sqlite",
    }
    _write_bundle(
        paths["security-lite"],
        profile="security-lite",
        version="fixture-security-v1",
    )
    _write_bundle(
        paths["github-lite"],
        profile="github-lite",
        version="fixture-github-v1",
    )
    manifest = _synthetic_manifest(paths)
    source_by_name = {path.name: path for path in paths.values()}

    def fetch(snapshot: object, _destination: Path) -> Path:
        return source_by_name[snapshot.repository_file]  # type: ignore[attr-defined]

    cache = SkillCenterSnapshotCache(tmp_path / "cache", fetcher=fetch)
    return (
        SkillCenterPilot(
            manifest,
            cache=cache,
            store=RecordingStore(),
        ),
        manifest,
    )


def test_committed_manifest_pins_exact_two_small_bundle_hashes() -> None:
    manifest = SkillCenterPilotManifest.from_path(FIXTURE_MANIFEST)

    assert manifest.dataset_revision == REVISION
    assert manifest.total_skills == 2114
    assert manifest.sample_records == 32
    assert {item.profile for item in manifest.bundles} == {
        "security-lite",
        "github-lite",
    }
    assert all(len(item.expected_sha256) == 64 for item in manifest.bundles)
    assert manifest.expansion_policy.prohibited_repository_files == (
        GITHUB_ALL_FILENAME,
    )
    assert (
        SkillCenterPilotManifest.from_json(
            json.dumps(manifest.to_dict())
        ).manifest_sha256
        == manifest.manifest_sha256
    )


def test_sample_then_full_reports_reproducible_policy_and_grounding(
    offline_pilot: tuple[SkillCenterPilot, SkillCenterPilotManifest],
) -> None:
    pilot, manifest = offline_pilot

    first_sample = pilot.run_sample()
    second_sample = pilot.run(PilotRunMode.SAMPLE)
    full = pilot.run_full(first_sample)

    assert first_sample.passed
    assert first_sample.selected_record_count == manifest.sample_records == 2
    assert first_sample.evidence_sha256 == second_sample.evidence_sha256
    assert first_sample.elapsed_ms >= 0
    assert first_sample.process_peak_memory_bytes > 0
    assert not first_sample.github_all_expansion_permitted

    assert full.passed
    assert full.selected_record_count == manifest.total_skills == 4
    assert dict(full.rollout_gates) == {
        "quality": True,
        "safety": True,
        "license": True,
        "throughput": True,
        "reproducibility": True,
    }
    assert not full.github_all_expansion_permitted
    for bundle in full.bundles:
        assert bundle.snapshot_verified
        assert bundle.policy_evaluated_count == 2
        assert bundle.normalized_record_count == 1
        assert bundle.policy_blocked_count == 1
        assert bundle.policy_decision_counts["allow_train_and_publish"] == 1
        assert bundle.policy_decision_counts["quarantined_unknown"] == 1
        assert bundle.grounding.grounded_statement_count > 0
        assert bundle.grounding.grounded_action_count == 2
        assert (
            bundle.grounding.source_ref_count
            == bundle.grounding.source_span_count
        )
        assert bundle.corpus_graph_digest.startswith("sha256:")
        assert bundle.corpus_graph_cid
        assert bundle.semantic_graph_digests
        assert bundle.semantic_graph_cids
        assert not bundle.failures


def test_full_requires_same_manifest_successful_sample(
    offline_pilot: tuple[SkillCenterPilot, SkillCenterPilotManifest],
) -> None:
    pilot, _manifest = offline_pilot

    with pytest.raises(SkillCenterPilotGateError, match="sample receipt"):
        pilot.run_full(None)  # type: ignore[arg-type]

    sample = pilot.run_sample()
    with pytest.raises(SkillCenterPilotGateError, match="different"):
        pilot.run_full(replace(sample, manifest_sha256="0" * 64))


def test_manifest_rejects_github_all_even_when_hash_and_size_are_pinned(
    offline_pilot: tuple[SkillCenterPilot, SkillCenterPilotManifest],
) -> None:
    _pilot, manifest = offline_pilot
    github_lite = next(
        item for item in manifest.bundles if item.profile == "github-lite"
    )

    with pytest.raises(SkillCenterPilotManifestError, match="GitHub-all"):
        replace(github_lite, repository_file=GITHUB_ALL_FILENAME)
