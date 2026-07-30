"""KGP-034: Compatibility policy, deprecation windows, and runbook publication.

Regression coverage for ``ipfs_datasets_py.knowledge_graphs.compat`` and the
published migration / release runbooks. Placeholders or weakened assertions
are out of scope — this module is the acceptance validator for the task.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs import compat as compat_mod
from ipfs_datasets_py.knowledge_graphs.compat import (
    ANNOUNCE_DATE,
    CANONICAL_SERVICE,
    CANONICAL_TARGET,
    DEFAULT_REMOVAL_EARLIEST,
    DEFAULT_STORAGE_PROFILE,
    DISPOSITIONS,
    FORWARD_PHASES,
    LEGACY_MAP,
    MANDATORY_DISPOSITIONS,
    MANDATORY_LEGACY_IDS,
    MIGRATION_PHASES,
    ONE_SERVICE_RULE,
    PACKAGE_MIN_REMOVE_FLOOR,
    PACKAGE_WARN_BASELINE,
    POLICY_VERSION,
    PRODUCER_MAP,
    STORAGE_PROFILES,
    TIERS,
    CompatPolicyError,
    assert_policy_invariants,
    can_enter_phase,
    compare_versions,
    deprecation_message,
    get_legacy,
    get_producer,
    legacy_ids_for_path,
    list_legacy_ids,
    list_producer_ids,
    minor_releases_between,
    phase_index,
    policy_dict,
    removal_allowed,
    resolve_storage_profile,
    same_release_warn_remove_forbidden,
    validate_storage_profile,
    warn_legacy,
    window_for_legacy,
    all_warning_windows,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = REPO_ROOT / "docs" / "migration" / "knowledge_graphs"
RELEASE_DOC = REPO_ROOT / "docs" / "operations" / "knowledge_graphs_release.md"
COMPAT_ADR = REPO_ROOT / "docs" / "architecture" / "knowledge_graphs_compatibility.md"
COMPAT_PY = REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs" / "compat.py"

REQUIRED_MIGRATION_DOCS = (
    "README.md",
    "compatibility.md",
    "migration_runbook.md",
    "producers.md",
    "schema_storage_ucan.md",
)


# ---------------------------------------------------------------------------
# Policy core
# ---------------------------------------------------------------------------


def test_policy_version_and_one_service_rule() -> None:
    assert POLICY_VERSION == "kg-compatibility/v1"
    assert ONE_SERVICE_RULE is True
    assert CANONICAL_SERVICE == "GraphService"
    assert CANONICAL_TARGET == "GraphTarget"
    assert TIERS == ("T0", "T1", "T2", "T3")
    assert DISPOSITIONS == ("adopt", "adapt", "deprecate")
    assert_policy_invariants()


def test_policy_dict_is_json_serializable_and_complete() -> None:
    policy = policy_dict()
    encoded = json.dumps(policy, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["policy_version"] == "kg-compatibility/v1"
    assert decoded["one_service_rule"] is True
    assert decoded["canonical_service"] == "GraphService"
    assert decoded["canonical_target"] == "GraphTarget"
    assert decoded["same_release_warn_and_remove_forbidden"] is True
    assert decoded["min_warn_minor_releases"] == 1
    assert set(decoded["storage_profiles"]) == set(STORAGE_PROFILES)
    assert decoded["default_storage_profile"] == DEFAULT_STORAGE_PROFILE

    legacy = decoded["legacy_map"]
    for key, disposition in MANDATORY_DISPOSITIONS.items():
        assert key in legacy
        assert legacy[key]["disposition"] == disposition
        assert legacy[key]["tier"] in TIERS
        assert legacy[key]["paths"]
        assert legacy[key]["replacement"]

    assert "warning_windows" in decoded
    assert len(decoded["warning_windows"]) >= 3
    assert "producers" in decoded
    assert "cvefixes_security_ir_graphrag" in decoded["producers"]
    assert decoded["runbooks"]["migration"].startswith("docs/migration/")
    assert decoded["runbooks"]["release"].endswith("knowledge_graphs_release.md")


def test_mandatory_legacy_map_matches_adr_dispositions() -> None:
    assert MANDATORY_LEGACY_IDS <= set(LEGACY_MAP)
    for legacy_id, expected in MANDATORY_DISPOSITIONS.items():
        entry = get_legacy(legacy_id)
        assert entry.disposition == expected
        assert entry.tier in TIERS
        assert entry.paths
        assert entry.replacement

    # KnowledgeGraphManager must be deprecate / T2 for one-service rule.
    kgm = get_legacy("knowledge_graph_manager")
    assert kgm.disposition == "deprecate"
    assert kgm.tier == "T2"
    assert "GraphService" in kgm.replacement or "Client" in kgm.replacement


def test_list_legacy_ids_sorted_and_path_lookup() -> None:
    ids = list_legacy_ids()
    assert ids == sorted(ids)
    assert "graph_engine" in ids

    hits = legacy_ids_for_path(
        "ipfs_datasets_py/knowledge_graphs/core/graph_engine.py"
    )
    assert "graph_engine" in hits

    hits2 = legacy_ids_for_path(
        "ipfs_datasets_py/core_operations/knowledge_graph_manager.py"
    )
    assert "knowledge_graph_manager" in hits2


def test_unknown_legacy_and_producer_errors() -> None:
    with pytest.raises(CompatPolicyError) as exc:
        get_legacy("not_a_real_legacy")
    assert exc.value.code == "UNKNOWN_LEGACY"

    with pytest.raises(CompatPolicyError) as exc2:
        get_producer("not_a_real_producer")
    assert exc2.value.code == "UNKNOWN_PRODUCER"


# ---------------------------------------------------------------------------
# Version / removal windows
# ---------------------------------------------------------------------------


def test_compare_versions_and_minor_distance() -> None:
    assert compare_versions("0.1.0", "0.1.0") == 0
    assert compare_versions("0.1.0", "0.2.0") == -1
    assert compare_versions("0.2.0", "0.1.0") == 1
    assert compare_versions("v0.1.0", "0.1.0") == 0

    assert minor_releases_between("0.1.0", "0.2.0") == 1
    assert minor_releases_between("0.1.0", "0.3.1") == 2
    assert minor_releases_between("0.1.0", "0.1.5") == 0
    assert minor_releases_between("0.2.0", "0.1.0") == 0

    with pytest.raises(CompatPolicyError) as exc:
        minor_releases_between("0.1.0", "1.0.0")
    assert exc.value.code == "MAJOR_CROSSING"


def test_same_release_warn_remove_forbidden() -> None:
    assert same_release_warn_remove_forbidden("0.1.0", "0.1.0") is True
    assert same_release_warn_remove_forbidden("0.1.0", "0.2.0") is False


def test_warning_windows_exist_for_deprecated_public_names() -> None:
    windows = {w.legacy_id: w for w in all_warning_windows()}
    assert "knowledge_graph_manager" in windows
    assert "data_transformation_ipld_graph" in windows
    assert "legacy_root_reexports" in windows

    for window in windows.values():
        assert window.min_warn_minor_releases >= 1
        assert window.same_release_warn_and_remove_forbidden is True
        assert compare_versions(
            window.remove_after_version, window.warn_since_version
        ) > 0
        assert window.removal_earliest


def test_removal_allowed_enforces_one_minor_and_calendar_floor() -> None:
    legacy_id = "knowledge_graph_manager"
    window = window_for_legacy(legacy_id)
    assert window is not None
    assert window.warn_since_version == PACKAGE_WARN_BASELINE
    assert window.remove_after_version == PACKAGE_MIN_REMOVE_FLOOR

    # Same release as first warn → forbidden
    assert not removal_allowed(legacy_id, package_version=PACKAGE_WARN_BASELINE)

    # Before remove floor
    assert not removal_allowed(legacy_id, package_version="0.1.9")

    # At remove floor but before calendar floor
    assert not removal_allowed(
        legacy_id,
        package_version=PACKAGE_MIN_REMOVE_FLOOR,
        calendar_date="2026-09-01",
    )

    # At remove floor and calendar floor
    assert removal_allowed(
        legacy_id,
        package_version=PACKAGE_MIN_REMOVE_FLOOR,
        calendar_date=DEFAULT_REMOVAL_EARLIEST,
    )

    # Security receipt bypasses floors
    assert removal_allowed(
        legacy_id,
        package_version="0.1.1",
        security_receipt=True,
    )

    # Non-warn-path legacy cannot be "removed" via window API
    assert window_for_legacy("graph_engine") is None
    assert not removal_allowed("graph_engine", package_version="9.0.0")


def test_policy_entries_never_warn_and_remove_same_release() -> None:
    """Conflict policy: no legacy entry may share warn and remove versions."""

    for entry in LEGACY_MAP.values():
        if entry.warn_since_version and entry.remove_after_version:
            assert not same_release_warn_remove_forbidden(
                entry.warn_since_version,
                entry.remove_after_version,
            )
            assert (
                compare_versions(
                    entry.remove_after_version,
                    entry.warn_since_version,
                )
                > 0
            )


def test_deprecation_warning_emission() -> None:
    msg = deprecation_message("knowledge_graph_manager")
    assert "kg-compatibility/v1" in msg
    assert "GraphService" in msg or "Client" in msg
    assert PACKAGE_WARN_BASELINE in msg

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_legacy("knowledge_graph_manager")
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert any("deprecated" in str(w.message).lower() for w in caught)

    # T1 adapt components should not spam warnings via warn_legacy
    with warnings.catch_warnings(record=True) as caught2:
        warnings.simplefilter("always")
        warn_legacy("graph_engine")
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught2)


# ---------------------------------------------------------------------------
# Storage profiles
# ---------------------------------------------------------------------------


def test_storage_profiles_align_with_service_contract() -> None:
    expected = {"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"}
    assert set(STORAGE_PROFILES) == expected
    assert DEFAULT_STORAGE_PROFILE == "parquet"
    assert resolve_storage_profile(None) == "parquet"
    assert resolve_storage_profile("hybrid") == "hybrid"
    assert validate_storage_profile("ipfs_kit") == "ipfs_kit"
    assert validate_storage_profile(None) is None

    with pytest.raises(CompatPolicyError) as exc:
        validate_storage_profile("s3")
    assert exc.value.code == "BAD_STORAGE_PROFILE"

    guidance = policy_dict()["storage_profile_guidance"]
    for profile in expected:
        assert profile in guidance
        assert "use_when" in guidance[profile]


# ---------------------------------------------------------------------------
# Producers and migration phases
# ---------------------------------------------------------------------------


def test_producer_map_covers_inventory_corpora() -> None:
    ids = set(list_producer_ids())
    for required in (
        "cvefixes_security_ir_graphrag",
        "skillcenter_ir_graphrag",
        "two11_retrieval_package",
        "two11_browser_graphrag",
        "supervisor_objective_graph",
        "supervisor_code_evidence_graph",
    ):
        assert required in ids
        producer = get_producer(required)
        assert producer.storage_profile_default in STORAGE_PROFILES
        assert producer.required_evidence
        assert producer.migration_risk in {"low", "medium", "high"}

    cve = get_producer("cvefixes_security_ir_graphrag")
    assert cve.fixture_only_producer is True
    assert "ucan_negative_proof" in cve.required_evidence


def test_migration_phase_ordering_and_gates() -> None:
    assert FORWARD_PHASES == (
        "prerequisites",
        "backup",
        "dry_run",
        "shadow",
        "canary",
        "cutover",
    )
    assert "rollback" in MIGRATION_PHASES
    assert phase_index("backup") == 1
    assert phase_index("cutover") == 5

    with pytest.raises(CompatPolicyError) as exc:
        phase_index("rollback")
    assert exc.value.code == "ROLLBACK_NOT_FORWARD"

    # Rollback always allowed
    assert can_enter_phase("rollback", completed_phases=[]) is True

    # Cannot skip backup
    assert not can_enter_phase(
        "dry_run", completed_phases=["prerequisites"]
    )
    assert can_enter_phase(
        "dry_run", completed_phases=["prerequisites", "backup"]
    )

    # Cutover requires producer evidence when producer_id given
    phases = list(FORWARD_PHASES[:-1])
    assert not can_enter_phase(
        "cutover",
        completed_phases=phases,
        producer_id="skillcenter_ir_graphrag",
        evidence=["schema_v2_v3_compat"],
    )
    assert can_enter_phase(
        "cutover",
        completed_phases=phases,
        producer_id="skillcenter_ir_graphrag",
        evidence=[
            "schema_v2_v3_compat",
            "graph_vector_bm25_parity",
            "differential_reader_parity",
            "backup_restore_proof",
        ],
    )


# ---------------------------------------------------------------------------
# Published runbooks (docs)
# ---------------------------------------------------------------------------


def test_migration_docs_directory_published() -> None:
    assert MIGRATION_DIR.is_dir(), f"missing {MIGRATION_DIR}"
    for name in REQUIRED_MIGRATION_DOCS:
        path = MIGRATION_DIR / name
        assert path.is_file(), f"missing migration doc {path}"
        text = path.read_text(encoding="utf-8")
        assert len(text) > 200, f"{path} looks like a stub"
        assert "KGP-034" in text or "kg-compatibility/v1" in text


def test_migration_runbook_covers_required_topics() -> None:
    combined = "\n".join(
        (MIGRATION_DIR / name).read_text(encoding="utf-8")
        for name in REQUIRED_MIGRATION_DOCS
    )
    lower = combined.lower()
    for topic in (
        "prerequisite",
        "backup",
        "dry-run",
        "dry_run",
        "shadow",
        "canary",
        "cutover",
        "rollback",
        "schema",
        "storage",
        "ucan",
        "on-call",
    ):
        assert topic.lower() in lower, f"migration docs missing topic {topic!r}"

    # Phase content must reference real modules
    assert "ShadowReader" in combined or "shadow" in lower
    assert "CanaryController" in combined or "cas_set_head" in combined
    assert "GraphService" in combined
    assert "kg-compatibility/v1" in combined


def test_compatibility_doc_publishes_tiers_and_windows() -> None:
    text = (MIGRATION_DIR / "compatibility.md").read_text(encoding="utf-8")
    for token in (
        "T0",
        "T1",
        "T2",
        "T3",
        "adopt",
        "adapt",
        "deprecate",
        "kg-compatibility/v1",
        "knowledge_graph_manager",
        PACKAGE_WARN_BASELINE,
        PACKAGE_MIN_REMOVE_FLOOR,
        DEFAULT_REMOVAL_EARLIEST,
        "same release",
    ):
        assert token in text, f"compatibility.md missing {token!r}"


def test_producers_doc_lists_inventory_corpora() -> None:
    text = (MIGRATION_DIR / "producers.md").read_text(encoding="utf-8")
    for producer_id in PRODUCER_MAP:
        assert producer_id in text
    assert "fixture-only" in text.lower() or "fixture_only" in text


def test_schema_storage_ucan_doc() -> None:
    text = (MIGRATION_DIR / "schema_storage_ucan.md").read_text(encoding="utf-8")
    for token in (
        "parquet",
        "ipfs_ipld",
        "ipfs_kit",
        "hybrid",
        "graph/query",
        "kg://",
        "GraphAuthorizationService",
        "schema",
    ):
        assert token in text, f"schema_storage_ucan.md missing {token!r}"


def test_release_doc_published_with_oncall_and_deprecation() -> None:
    assert RELEASE_DOC.is_file(), f"missing {RELEASE_DOC}"
    text = RELEASE_DOC.read_text(encoding="utf-8")
    assert len(text) > 500
    assert "KGP-034" in text
    assert "kg-compatibility/v1" in text
    lower = text.lower()
    for token in (
        "on-call",
        "cutover",
        "rollback",
        "deprecat",
        "shadow",
        "canary",
        "ucan",
        "storage",
        "backup",
        "producer",
    ):
        assert token in lower, f"release doc missing {token!r}"
    assert "removal_allowed" in text or "same release" in lower
    assert "knowledge_graphs_runbook" in text


def test_compat_module_file_exists_and_exports() -> None:
    assert COMPAT_PY.is_file()
    for name in (
        "POLICY_VERSION",
        "LEGACY_MAP",
        "PRODUCER_MAP",
        "policy_dict",
        "removal_allowed",
        "can_enter_phase",
        "assert_policy_invariants",
        "warn_legacy",
    ):
        assert hasattr(compat_mod, name)


def test_policy_aligned_with_compatibility_adr_when_present() -> None:
    """If the ADR is readable, the five-way map dispositions must match."""

    if not COMPAT_ADR.is_file():
        pytest.skip("compatibility ADR not present in this worktree snapshot")
    text = COMPAT_ADR.read_text(encoding="utf-8")
    assert "kg-compatibility/v1" in text
    marker = '"policy_version": "kg-compatibility/v1"'
    if marker not in text:
        pytest.skip("ADR missing machine-readable block")
    json_start = text.rfind("```json", 0, text.index(marker))
    json_fence = text.index("```", text.index(marker))
    block = text[text.index("{", json_start) : json_fence]
    adr_policy = json.loads(block)
    for key, disposition in MANDATORY_DISPOSITIONS.items():
        assert adr_policy["legacy_map"][key]["disposition"] == disposition
        assert (
            LEGACY_MAP[key].disposition
            == adr_policy["legacy_map"][key]["disposition"]
        )


def test_announce_and_warn_dates_are_iso() -> None:
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    assert iso.match(ANNOUNCE_DATE)
    assert iso.match(DEFAULT_REMOVAL_EARLIEST)
    assert ANNOUNCE_DATE <= DEFAULT_REMOVAL_EARLIEST
