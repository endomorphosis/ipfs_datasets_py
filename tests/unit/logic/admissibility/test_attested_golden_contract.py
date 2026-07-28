"""Structural golden contract for AttestedAuthorizationGoldenCorpus@1 (LIG-040).

This suite freezes the synthetic golden/adversarial corpus used by later
attested-authorization conformance and release gates.  It does **not** execute
skills, prompts, MCP tools, optional solvers, or network I/O.  It validates:

* canonical manifest/cases identity and schema;
* required coverage (invocation equivalence, authority lifecycles, capability
  scopes, adversarial integrity, ZKP classes, concurrency);
* bound expected filters, obligations, and wire outcomes;
* source / license / privacy metadata;
* relevant vs irrelevant mutation expectations;
* non-execution and fail-closed "cannot allow" invariants.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

import pytest

from ipfs_datasets_py.logic.admissibility.reasons import (
    AdmissibilityStatus,
    default_status_for_reason,
    parse_reason_code,
    parse_status,
    reason_code_set,
)


# ---------------------------------------------------------------------------
# Fixture paths and closed contract constants
# ---------------------------------------------------------------------------

FIXTURE_DIR: Final = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "logic"
    / "attested_authorization"
)
MANIFEST_PATH: Final = FIXTURE_DIR / "manifest.json"
CASES_PATH: Final = FIXTURE_DIR / "cases.json"

MANIFEST_INTERFACE: Final = "AttestedAuthorizationGoldenCorpus@1"
MANIFEST_SCHEMA: Final = "attested-authorization-golden-corpus/v1"
CASES_INTERFACE: Final = "AttestedAuthorizationGoldenCases@1"
CASES_SCHEMA: Final = "attested-authorization-golden-cases/v1"
CORPUS_ID: Final = "attested-authorization-golden-v1"

WIRE_STATUSES: Final = frozenset({"allow", "reject", "abstain"})
INVOCATION_KINDS: Final = frozenset({"skillcenter", "prompt", "mcp_tool"})

REQUIRED_MANIFEST_KEYS: Final = (
    "schema_version",
    "interface",
    "corpus_id",
    "corpus_revision",
    "description",
    "license",
    "privacy",
    "non_execution",
    "bound_interfaces",
    "wire_status_vocabulary",
    "reason_code_vocabulary",
    "cases_path",
    "cases_sha256",
    "case_ids",
    "case_index",
    "required_coverage",
    "equivalence_groups",
    "coverage_index",
    "evidence_subset",
    "depends_on_interfaces",
    "task_id",
    "goal_id",
)

REQUIRED_CASE_KEYS: Final = (
    "case_id",
    "stratum",
    "categories",
    "tags",
    "description",
    "source",
    "invocation",
    "filters",
    "obligations",
    "authorities",
    "expected",
    "mutations",
    "non_execution",
)

REQUIRED_EXPECTED_KEYS: Final = (
    "status",
    "internal_status",
    "reason_codes",
    "filters_applied",
    "obligations_required",
    "cannot_allow",
    "grants_dispatch_capability",
)

REQUIRED_SOURCE_KEYS: Final = (
    "kind",
    "license_expression",
    "privacy_class",
    "contains_pii",
    "contains_secrets",
    "network_required",
    "private_tenant_data",
    "raw_prompt_body_present",
)

REQUIRED_COVERAGE: Final[dict[str, tuple[str, ...]]] = {
    "invocation_kinds": ("skillcenter", "prompt", "mcp_tool"),
    "authority_outcomes": (
        "allow",
        "deny",
        "conditional",
        "exception",
        "ambiguous",
        "conflicting",
        "missing",
        "expired",
        "superseded",
        "revoked",
    ),
    "capability_scopes": (
        "capability",
        "trust_zone",
        "data_egress",
        "filesystem",
        "network",
        "subprocess",
        "destructive",
        "rollback",
    ),
    "adversarial_integrity": (
        "poisoned_neighbors",
        "tamper",
        "wrong_root",
        "wrong_tenant",
        "wrong_audience",
        "wrong_tool",
        "wrong_arguments",
        "wrong_time",
        "wrong_environment",
        "cache_substitution",
    ),
    "zkp_classes": (
        "malformed_zkp",
        "real_zkp",
        "simulated_zkp",
        "circuit_mismatch",
        "vk_mismatch",
        "public_input_mismatch",
    ),
    "concurrency": ("replay", "race", "exhaustion"),
}

# Reasons that must never be the sole justification for allow.
NON_ALLOWING_REASONS: Final = frozenset(reason_code_set()) - frozenset(
    {"obligations_supported"}
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.is_file(), f"missing manifest: {MANIFEST_PATH}"
    return _load_json(MANIFEST_PATH)


@pytest.fixture(scope="module")
def cases_doc() -> dict[str, Any]:
    assert CASES_PATH.is_file(), f"missing cases: {CASES_PATH}"
    return _load_json(CASES_PATH)


@pytest.fixture(scope="module")
def cases(cases_doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = cases_doc["cases"]
    assert isinstance(raw, list) and raw, "cases must be a non-empty list"
    return raw


@pytest.fixture(scope="module")
def cases_by_id(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["case_id"]: c for c in cases}


# ---------------------------------------------------------------------------
# Manifest contract
# ---------------------------------------------------------------------------


def test_manifest_schema_and_interface(manifest: dict[str, Any]) -> None:
    assert manifest["schema_version"] == MANIFEST_SCHEMA
    assert manifest["interface"] == MANIFEST_INTERFACE
    assert manifest["corpus_id"] == CORPUS_ID
    assert manifest["task_id"] == "LIG-040"
    assert manifest["goal_id"] == "LIG-G120"
    for key in REQUIRED_MANIFEST_KEYS:
        assert key in manifest, f"manifest missing required key {key!r}"


def test_manifest_cases_digest_matches_file(manifest: dict[str, Any]) -> None:
    raw = CASES_PATH.read_bytes()
    assert manifest["cases_path"] == "cases.json"
    assert manifest["cases_sha256"] == _sha256_hex(raw)


def test_manifest_indexes_every_case(
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    case_ids = [c["case_id"] for c in cases]
    assert manifest["case_ids"] == case_ids
    assert len(manifest["case_ids"]) == len(set(manifest["case_ids"]))
    index_ids = [row["case_id"] for row in manifest["case_index"]]
    assert index_ids == case_ids
    for row, case in zip(manifest["case_index"], cases, strict=True):
        assert row["stratum"] == case["stratum"]
        assert row["expected_status"] == case["expected"]["status"]
        assert row["expected_reason_codes"] == case["expected"]["reason_codes"]
        assert row["invocation_kind"] == case["invocation"]["kind"]
        assert row["license_expression"] == case["source"]["license_expression"]
        assert row["privacy_class"] == case["source"]["privacy_class"]


def test_manifest_license_and_privacy_forbid_private_data(
    manifest: dict[str, Any],
) -> None:
    license_meta = manifest["license"]
    privacy = manifest["privacy"]
    assert license_meta["license_expression"]
    assert license_meta["source_class"] == "synthetic_fixture"
    assert privacy["privacy_class"] == "public_synthetic"
    assert privacy["contains_pii"] is False
    assert privacy["contains_secrets"] is False
    assert privacy["network_required"] is False
    assert privacy["private_data_allowed"] is False
    assert privacy["raw_prompt_bodies_allowed"] is False
    assert privacy["raw_tool_arguments_allowed"] is False
    assert privacy["argument_representation"] == "commitment_only"


def test_manifest_non_execution_guarantees(manifest: dict[str, Any]) -> None:
    ne = manifest["non_execution"]
    assert ne["executes_skills"] is False
    assert ne["executes_prompts"] is False
    assert ne["executes_mcp_tools"] is False
    assert ne["requires_optional_solver"] is False
    assert ne["requires_network"] is False
    assert ne["requires_paid_model"] is False
    assert ne["side_effects"] is False


def test_manifest_bound_interfaces_and_vocabularies(
    manifest: dict[str, Any],
) -> None:
    bound = manifest["bound_interfaces"]
    for key in (
        "decision",
        "gate",
        "receipt",
        "capability",
        "invocation_envelope",
        "proof_envelope",
        "reason",
        "composer",
        "portfolio",
    ):
        assert key in bound and isinstance(bound[key], str) and bound[key]
    assert set(manifest["wire_status_vocabulary"]) == WIRE_STATUSES
    assert set(manifest["reason_code_vocabulary"]) == reason_code_set()


def test_manifest_required_coverage_declares_acceptance_matrix(
    manifest: dict[str, Any],
) -> None:
    coverage = manifest["required_coverage"]
    for dimension, expected in REQUIRED_COVERAGE.items():
        assert dimension in coverage, f"missing coverage dimension {dimension}"
        assert list(coverage[dimension]) == list(expected)


def test_manifest_evidence_subset(manifest: dict[str, Any]) -> None:
    evidence = set(manifest["evidence_subset"])
    for item in (
        "golden_coverage",
        "canonical_manifest",
        "licensing_privacy",
        "relevant_irrelevant_mutation",
        "non_execution_receipt",
    ):
        assert item in evidence


# ---------------------------------------------------------------------------
# Cases document contract
# ---------------------------------------------------------------------------


def test_cases_document_schema(cases_doc: dict[str, Any]) -> None:
    assert cases_doc["schema_version"] == CASES_SCHEMA
    assert cases_doc["interface"] == CASES_INTERFACE
    assert cases_doc["corpus_id"] == CORPUS_ID
    assert isinstance(cases_doc["description"], str) and cases_doc["description"]


def test_every_case_has_required_structure(cases: list[dict[str, Any]]) -> None:
    closed_reasons = reason_code_set()
    for case in cases:
        for key in REQUIRED_CASE_KEYS:
            assert key in case, f"{case.get('case_id')}: missing {key}"
        assert case["stratum"] in {"golden", "adversarial"}
        assert isinstance(case["categories"], list) and case["categories"]
        assert case["categories"] == sorted(case["categories"])
        assert isinstance(case["tags"], list) and case["tags"]
        assert case["tags"] == sorted(case["tags"])
        assert isinstance(case["description"], str) and case["description"]

        source = case["source"]
        for key in REQUIRED_SOURCE_KEYS:
            assert key in source, f"{case['case_id']}: source missing {key}"
        assert source["kind"] == "synthetic"
        assert source["contains_pii"] is False
        assert source["contains_secrets"] is False
        assert source["network_required"] is False
        assert source["private_tenant_data"] is False
        assert source["raw_prompt_body_present"] is False
        assert source["license_expression"]

        inv = case["invocation"]
        assert inv["kind"] in {
            "skillcenter",
            "prompt",
            "mcp_tool",
            "composite",
            "unspecified",
        }
        for field in (
            "actor_id",
            "audience_id",
            "tenant_id",
            "tool_id",
            "tool_version",
            "argument_commitment",
            "environment_id",
            "policy_root",
            "corpus_roots",
            "revocation_root",
            "nonce",
            "created_at",
            "effective_at",
        ):
            assert field in inv and inv[field], f"{case['case_id']}: invocation.{field}"
        assert inv["argument_commitment"].startswith("sha256:")
        assert set(inv["corpus_roots"]) >= {"legal", "security", "intent"}

        assert isinstance(case["filters"], Mapping) and case["filters"]
        assert isinstance(case["obligations"], list)
        for obl in case["obligations"]:
            assert obl["obligation_id"]
            assert obl["kind"]
            assert obl["domain"] in {"legal", "security", "intent"}
            assert str(obl["statement_digest"]).startswith("sha256:")

        assert isinstance(case["authorities"], list)
        for auth in case["authorities"]:
            assert auth["authority_id"]
            assert auth["family"] in {"legal", "security", "intent"}
            assert "attestation_kind" in auth
            assert "result_status" in auth
            assert "authority_lifecycle" in auth or case["case_id"].startswith(
                "poisoned_"
            )

        expected = case["expected"]
        for key in REQUIRED_EXPECTED_KEYS:
            assert key in expected, f"{case['case_id']}: expected missing {key}"
        status = parse_status(expected["status"])
        assert status.value in WIRE_STATUSES
        assert expected["cannot_allow"] is (status is not AdmissibilityStatus.ALLOW)
        assert expected["grants_dispatch_capability"] is (
            status is AdmissibilityStatus.ALLOW
        )
        assert expected["reason_codes"], f"{case['case_id']}: empty reason_codes"
        for code in expected["reason_codes"]:
            assert code in closed_reasons
            parse_reason_code(code)
        assert isinstance(expected["filters_applied"], list) and expected["filters_applied"]
        assert isinstance(expected["obligations_required"], list)

        ne = case["non_execution"]
        assert ne["executes_skills"] is False
        assert ne["executes_prompts"] is False
        assert ne["executes_mcp_tools"] is False
        assert ne["side_effects"] is False

        mutations = case["mutations"]
        assert set(mutations) >= {"relevant", "irrelevant"}
        assert isinstance(mutations["relevant"], list)
        assert isinstance(mutations["irrelevant"], list)


def test_allow_cases_require_obligations_supported(
    cases: list[dict[str, Any]],
) -> None:
    for case in cases:
        if case["expected"]["status"] != "allow":
            continue
        assert "obligations_supported" in case["expected"]["reason_codes"]
        assert case["expected"]["cannot_allow"] is False
        assert case["expected"]["grants_dispatch_capability"] is True
        # Simulated / membership-only authorities must never appear on allow.
        for auth in case["authorities"]:
            assert auth.get("is_simulated") is not True
            assert auth.get("attestation_kind") != "simulation"
            assert auth.get("is_revoked") is not True
            assert auth.get("is_superseded") is not True
            assert auth.get("is_expired") is not True


def test_non_allow_cases_never_grant_dispatch(
    cases: list[dict[str, Any]],
) -> None:
    for case in cases:
        if case["expected"]["status"] == "allow":
            continue
        assert case["expected"]["cannot_allow"] is True
        assert case["expected"]["grants_dispatch_capability"] is False
        # At least one reason must be a non-allowing code.
        assert any(
            code in NON_ALLOWING_REASONS for code in case["expected"]["reason_codes"]
        )


def test_reason_codes_are_status_compatible(cases: list[dict[str, Any]]) -> None:
    """Default status for any listed reason must not promote reject→allow."""

    for case in cases:
        status = parse_status(case["expected"]["status"])
        defaults = [
            default_status_for_reason(code) for code in case["expected"]["reason_codes"]
        ]
        if status is AdmissibilityStatus.ALLOW:
            assert AdmissibilityStatus.ALLOW in defaults
            assert AdmissibilityStatus.REJECT not in defaults
        if status is AdmissibilityStatus.REJECT:
            # Reject may combine reject defaults; never only allow-defaults.
            assert any(d is AdmissibilityStatus.REJECT for d in defaults) or any(
                d is AdmissibilityStatus.ABSTAIN for d in defaults
            )


# ---------------------------------------------------------------------------
# Required coverage matrix
# ---------------------------------------------------------------------------


def _tags(cases: Iterable[Mapping[str, Any]]) -> set[str]:
    return {tag for case in cases for tag in case["tags"]}


def _categories(cases: Iterable[Mapping[str, Any]]) -> set[str]:
    return {cat for case in cases for cat in case["categories"]}


def test_coverage_skill_prompt_mcp_equivalence(
    cases: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    kinds = {c["invocation"]["kind"] for c in cases}
    for kind in REQUIRED_COVERAGE["invocation_kinds"]:
        assert kind in kinds, f"missing invocation kind {kind}"

    groups = manifest["equivalence_groups"]
    assert groups, "expected at least one skill/prompt/MCP equivalence group"
    for group_id, member_ids in groups.items():
        assert len(member_ids) >= 3, f"{group_id} must include skill/prompt/MCP"
        members = [c for c in cases if c["case_id"] in member_ids]
        assert len(members) == len(member_ids)
        member_kinds = {m["invocation"]["kind"] for m in members}
        assert INVOCATION_KINDS <= member_kinds
        # Shared obligation digests across representations.
        obl_sets = [
            tuple(sorted(o["statement_digest"] for o in m["obligations"]))
            for m in members
        ]
        assert len(set(obl_sets)) == 1, f"{group_id}: obligation digests diverge"
        statuses = {m["expected"]["status"] for m in members}
        assert statuses == {"allow"}


def test_coverage_authority_outcomes(cases: list[dict[str, Any]]) -> None:
    tags = _tags(cases)
    for outcome in REQUIRED_COVERAGE["authority_outcomes"]:
        assert outcome in tags, f"missing authority outcome tag {outcome!r}"


def test_coverage_capability_scopes(cases: list[dict[str, Any]]) -> None:
    tags = _tags(cases)
    categories = _categories(cases)
    for scope in REQUIRED_COVERAGE["capability_scopes"]:
        assert scope in tags or scope in categories, f"missing capability scope {scope}"


def test_coverage_adversarial_integrity(cases: list[dict[str, Any]]) -> None:
    tags = _tags(cases)
    for attack in REQUIRED_COVERAGE["adversarial_integrity"]:
        assert attack in tags, f"missing adversarial tag {attack}"
        matching = [c for c in cases if attack in c["tags"]]
        assert matching, attack
        for case in matching:
            assert case["expected"]["status"] != "allow"
            assert case["expected"]["cannot_allow"] is True
            assert "adversarial" in case or case.get("adversarial") is not None or (
                "adversarial" in case["tags"]
            )


def test_coverage_zkp_classes(cases: list[dict[str, Any]]) -> None:
    tags = _tags(cases)
    for zkp_class in REQUIRED_COVERAGE["zkp_classes"]:
        assert zkp_class in tags, f"missing zkp class {zkp_class}"
        matching = [c for c in cases if zkp_class in c["tags"]]
        assert matching
        for case in matching:
            assert "zkp" in case, f"{case['case_id']} missing zkp block"
            if zkp_class == "simulated_zkp":
                assert case["expected"]["status"] != "allow"
                assert any(
                    a.get("is_simulated") or a.get("attestation_kind") == "simulation"
                    for a in case["authorities"]
                )
            if zkp_class == "real_zkp":
                assert case["expected"]["status"] == "allow"
                assert case["zkp"]["is_simulated"] is False


def test_coverage_concurrency(cases: list[dict[str, Any]]) -> None:
    tags = _tags(cases)
    for item in REQUIRED_COVERAGE["concurrency"]:
        assert item in tags, f"missing concurrency tag {item}"
        matching = [c for c in cases if item in c["tags"]]
        assert matching
        for case in matching:
            assert "concurrency" in case
            assert case["expected"]["status"] != "allow"


def test_manifest_coverage_index_matches_cases(
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    index = manifest["coverage_index"]
    assert index["case_count"] == len(cases)
    assert set(index["strata"]) == {c["stratum"] for c in cases}
    assert set(index["wire_statuses"]) == {c["expected"]["status"] for c in cases}
    assert set(index["invocation_kinds_present"]) == {
        c["invocation"]["kind"] for c in cases
    }
    assert set(index["tags"]) == _tags(cases)
    assert set(index["categories"]) == _categories(cases)


# ---------------------------------------------------------------------------
# Filters, obligations, mutations, adversarial payloads
# ---------------------------------------------------------------------------


def test_expected_filters_and_obligations_are_bound(
    cases: list[dict[str, Any]],
) -> None:
    for case in cases:
        expected = case["expected"]
        for filt in expected["filters_applied"]:
            assert filt in case["filters"], (
                f"{case['case_id']}: filters_applied {filt!r} not in filters"
            )
        obl_ids = {o["obligation_id"] for o in case["obligations"]}
        for obl_id in expected["obligations_required"]:
            assert obl_id in obl_ids, (
                f"{case['case_id']}: required obligation {obl_id!r} missing"
            )


def test_metamorphic_mutations_declare_relevant_and_irrelevant(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    # Every allow equivalence member and the dedicated metamorphic case.
    targets = [
        cid
        for cid, case in cases_by_id.items()
        if case.get("equivalence_group") or cid == "metamorphic_relevant_vs_irrelevant"
    ]
    assert "metamorphic_relevant_vs_irrelevant" in targets
    for case_id in targets:
        case = cases_by_id[case_id]
        relevant = case["mutations"]["relevant"]
        irrelevant = case["mutations"]["irrelevant"]
        assert relevant, f"{case_id}: need relevant mutations"
        assert irrelevant, f"{case_id}: need irrelevant mutations"
        for mut in relevant:
            assert mut["expected_effect"] != "identity_stable"
            assert mut["path"]
            assert mut["operation"] == "set"
        for mut in irrelevant:
            assert mut["expected_effect"] == "identity_stable"


def test_adversarial_cases_bind_attack_metadata(
    cases: list[dict[str, Any]],
) -> None:
    for case in cases:
        if "adversarial_integrity" not in case["categories"]:
            continue
        assert case.get("adversarial"), f"{case['case_id']}: missing adversarial block"
        assert case["adversarial"]["attack"]
        assert case["expected"]["status"] in {"reject", "abstain"}


def test_cache_substitution_is_non_authoritative(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    case = cases_by_id["cache_substitution_membership_only"]
    assert case["expected"]["status"] != "allow"
    assert case["adversarial"]["attack"] == "cache_substitution"
    assert case["adversarial"]["substituted_kind"] == "artifact-membership"
    assert any(
        a.get("attestation_kind") == "artifact-membership" for a in case["authorities"]
    )


def test_zkp_mismatch_cases_bind_expected_vs_observed(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    for case_id, field in (
        ("zkp_circuit_mismatch", "circuit_id"),
        ("zkp_vk_mismatch", "vk_id"),
        ("zkp_public_input_mismatch", "public_inputs"),
    ):
        case = cases_by_id[case_id]
        assert case["expected"]["status"] != "allow"
        assert "zkp" in case
        assert case["authorities"], case_id
        auth = case["authorities"][0]
        assert field in auth or field in case["zkp"]


def test_expired_superseded_revoked_never_allow(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    for case_id, flag in (
        ("expired_authority_window", "is_expired"),
        ("superseded_authority_parent", "is_superseded"),
        ("revoked_authority_root", "is_revoked"),
    ):
        case = cases_by_id[case_id]
        assert case["expected"]["status"] == "reject"
        assert any(a.get(flag) is True for a in case["authorities"])


def test_no_private_or_secret_material_in_payloads(
    cases: list[dict[str, Any]],
) -> None:
    """Corpus must remain public-synthetic: no raw secrets or PII-shaped blobs."""

    blob = json.dumps(cases, sort_keys=True)
    forbidden_substrings = (
        "BEGIN PRIVATE KEY",
        "AKIA",
        "ghp_",
        "sk-proj-",
        "password=",
        "Bearer ey",
    )
    for token in forbidden_substrings:
        assert token not in blob
    for case in cases:
        commitment = case["invocation"]["argument_commitment"]
        assert commitment.startswith("sha256:")
        assert " " not in commitment


def test_corpus_is_sorted_and_deterministic(
    cases: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    ids = [c["case_id"] for c in cases]
    assert ids == sorted(ids)
    # Re-serialize cases with the same canonical policy and compare digest.
    cases_doc = _load_json(CASES_PATH)
    reserialized = json.dumps(
        cases_doc, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")
    if not reserialized.endswith(b"\n"):
        reserialized += b"\n"
    assert _sha256_hex(reserialized) == manifest["cases_sha256"]


def test_coverage_minimum_case_count(cases: list[dict[str, Any]]) -> None:
    # Lower bound: one case per required tag across all dimensions plus triad + metamorphic.
    min_required = (
        3  # skill/prompt/mcp triad
        + len(REQUIRED_COVERAGE["authority_outcomes"])
        + len(REQUIRED_COVERAGE["capability_scopes"])
        + len(REQUIRED_COVERAGE["adversarial_integrity"])
        + len(REQUIRED_COVERAGE["zkp_classes"])
        + len(REQUIRED_COVERAGE["concurrency"])
    )
    # Overlap is expected (triad also tags allow); still require a healthy corpus size.
    assert len(cases) >= 35
    assert len(cases) >= min_required - 10


def test_default_status_mapping_not_weakened_by_allow_only_adversarial(
    cases: list[dict[str, Any]],
) -> None:
    """Adversarial strata must not declare allow."""

    for case in cases:
        if case["stratum"] != "adversarial":
            continue
        assert case["expected"]["status"] != "allow", case["case_id"]
        assert case["expected"]["cannot_allow"] is True


def test_simulated_zkp_cases_never_allow_or_grant_capability(
    cases: list[dict[str, Any]],
) -> None:
    """LIG-041 release gate: simulated ZKP evidence cannot authorize production."""

    hit = 0
    for case in cases:
        authorities = case.get("authorities") or []
        simulated = any(
            bool(a.get("is_simulated"))
            or str(a.get("attestation_kind", "")).lower()
            in {"simulation", "simulated"}
            or str(a.get("result_authority", "")).lower()
            in {"simulation", "simulated"}
            for a in authorities
        )
        tags = set(case.get("tags") or [])
        if not simulated and "simulated_zkp" not in tags:
            continue
        hit += 1
        exp = case["expected"]
        assert exp["status"] != "allow", case["case_id"]
        assert exp["cannot_allow"] is True
        assert exp["grants_dispatch_capability"] is False
    assert hit >= 1, "expected at least one simulated-ZKP fixture"


def test_package_root_exports_include_gate_and_rollout_symbols() -> None:
    """LIG-041: package facade must expose gate + rollout without leaf imports."""

    import ipfs_datasets_py.logic.admissibility as adm

    for name in (
        "IntentAdmissibilityGate",
        "evaluate_admissibility",
        "AdmissibilityStatus",
        "AuthorizationRolloutPolicy",
        "default_rollout_policy",
        "IntentAuthorizationService",
        "NON_ALLOWING_AUTHORITY_PATHS",
    ):
        assert name in adm.__all__, name
        assert getattr(adm, name) is not None
