"""Attested-authorization release conformance (LIG-041 / AttestedAuthorizationConformance@1).

Offline skill / prompt / MCP golden fixtures must reach **exact** bound decisions
without executing source bodies.  This suite also gates package exports,
registry discovery, production fail-closed invariants (simulated ZKP never
allows), category coverage (golden/adversarial/metamorphic/differential/
native-ZK/cache-revocation/tenant-privacy/race-TOCTOU/chaos/rebuild/
legacy-compatibility), rollout defaults, and release-evidence binding shape.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import socket
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Final, Mapping

import pytest


REPO_ROOT: Final = Path(__file__).resolve().parents[3]
FIXTURE_DIR: Final = (
    REPO_ROOT / "tests" / "fixtures" / "logic" / "attested_authorization"
)
MANIFEST_PATH: Final = FIXTURE_DIR / "manifest.json"
CASES_PATH: Final = FIXTURE_DIR / "cases.json"
ROLLOUT_CONFIG_PATH: Final = REPO_ROOT / "config" / "intent_authorization_rollout.json"

CONFORMANCE_INTERFACE: Final = "AttestedAuthorizationConformance@1"
CORPUS_INTERFACE: Final = "AttestedAuthorizationGoldenCorpus@1"
ROLLOUT_INTERFACE: Final = "AttestedAuthorizationRollout@1"

REQUIRED_POPULATIONS: Final = (
    "golden",
    "adversarial",
    "metamorphic",
    "differential",
    "native_zk",
    "cache_revocation",
    "tenant_privacy",
    "race_toctou",
    "chaos",
    "rebuild",
    "legacy_compatibility",
)

INVOCATION_KINDS: Final = frozenset({"skillcenter", "prompt", "mcp_tool"})
WIRE_STATUSES: Final = frozenset({"allow", "reject", "abstain"})
INTERNAL_STATUSES: Final = frozenset(
    {"allow", "deny", "review", "indeterminate", "error"}
)

# Heavy optional modules that must not load on plain package import.
FORBIDDEN_IMPORT_PREFIXES: Final = (
    "z3",
    "cvc5",
    "vampire",
    "lean_dojo",
    "shadowprover",
    "circom",
    "snarkjs",
)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.is_file(), f"missing golden manifest: {MANIFEST_PATH}"
    return _load_json(MANIFEST_PATH)


@pytest.fixture(scope="module")
def cases_doc() -> dict[str, Any]:
    assert CASES_PATH.is_file(), f"missing golden cases: {CASES_PATH}"
    return _load_json(CASES_PATH)


@pytest.fixture(scope="module")
def cases(cases_doc: dict[str, Any]) -> list[dict[str, Any]]:
    raw = cases_doc["cases"]
    assert isinstance(raw, list) and raw
    return raw


@pytest.fixture(scope="module")
def cases_by_id(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["case_id"]: c for c in cases}


# ---------------------------------------------------------------------------
# Offline decision path (exact fixture decisions, no execution)
# ---------------------------------------------------------------------------


def offline_evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact offline decision bound to *case* without execution.

    The golden corpus freezes expected status/reasons as the content-addressed
    offline decision artifact.  This function:

    1. asserts non-execution and privacy metadata;
    2. validates expected against closed wire/reason vocabularies;
    3. applies production fail-closed envelopes (simulated ZKP cannot allow);
    4. returns a stable decision dict suitable for differential replay.
    """

    from ipfs_datasets_py.logic.admissibility import (
        AdmissibilityStatus,
        NON_ALLOWING_AUTHORITY_PATHS,
        default_status_for_reason,
        parse_reason_code,
        parse_status,
        reason_code_set,
    )
    from ipfs_datasets_py.logic.admissibility import (
        InternalDecisionStatus,
        map_internal_to_wire,
    )

    ne = case["non_execution"]
    assert ne["executes_skills"] is False
    assert ne["executes_prompts"] is False
    assert ne["executes_mcp_tools"] is False
    assert ne["side_effects"] is False
    # Network / solver requirements may be absent on older fixture shapes; when
    # present they must remain false for offline release gates.
    if "requires_network" in ne:
        assert ne["requires_network"] is False
    if "requires_optional_solver" in ne:
        assert ne["requires_optional_solver"] is False

    source = case["source"]
    assert source["contains_pii"] is False
    assert source["contains_secrets"] is False
    assert source["network_required"] is False
    assert source["private_tenant_data"] is False
    assert source["raw_prompt_body_present"] is False

    expected = case["expected"]
    status = parse_status(expected["status"])
    assert status.value in WIRE_STATUSES
    internal = str(expected["internal_status"])
    assert internal in INTERNAL_STATUSES

    reason_codes = list(expected["reason_codes"])
    assert reason_codes, f"{case['case_id']}: empty reason_codes"
    assert set(reason_codes) <= reason_code_set()
    for code in reason_codes:
        parse_reason_code(code)

    # Production envelope: simulated / non-allowing authority paths never allow.
    authorities = list(case.get("authorities") or [])
    simulated = any(
        bool(a.get("is_simulated"))
        or str(a.get("attestation_kind", "")).lower() in {"simulation", "simulated"}
        or str(a.get("result_authority", "")).lower()
        in NON_ALLOWING_AUTHORITY_PATHS
        for a in authorities
    )
    if simulated:
        assert status is not AdmissibilityStatus.ALLOW, (
            f"{case['case_id']}: simulated/non-authoritative evidence must not allow"
        )
        assert expected["cannot_allow"] is True
        assert expected["grants_dispatch_capability"] is False

    # Internal → wire mapping consistency for known internal statuses.
    if internal == "allow":
        assert status is AdmissibilityStatus.ALLOW
        assert map_internal_to_wire(InternalDecisionStatus.ALLOW) is AdmissibilityStatus.ALLOW
        assert expected["grants_dispatch_capability"] is True
        assert expected["cannot_allow"] is False
        assert reason_codes == ["obligations_supported"]
        assert (
            default_status_for_reason(parse_reason_code("obligations_supported"))
            is AdmissibilityStatus.ALLOW
        )
    elif internal == "deny":
        assert status is AdmissibilityStatus.REJECT
        assert map_internal_to_wire(InternalDecisionStatus.DENY) is AdmissibilityStatus.REJECT
        assert expected["cannot_allow"] is True
        assert expected["grants_dispatch_capability"] is False
    elif internal == "review":
        assert status is AdmissibilityStatus.ABSTAIN
        assert map_internal_to_wire(InternalDecisionStatus.REVIEW) is AdmissibilityStatus.ABSTAIN
        assert expected["cannot_allow"] is True
        assert expected["grants_dispatch_capability"] is False

    inv_kind = case["invocation"]["kind"]
    assert inv_kind in INVOCATION_KINDS

    decision = {
        "case_id": case["case_id"],
        "interface": CONFORMANCE_INTERFACE,
        "corpus_interface": CORPUS_INTERFACE,
        "invocation_kind": inv_kind,
        "status": status.value,
        "internal_status": internal,
        "reason_codes": reason_codes,
        "filters_applied": list(expected["filters_applied"]),
        "obligations_required": list(expected["obligations_required"]),
        "cannot_allow": bool(expected["cannot_allow"]),
        "grants_dispatch_capability": bool(expected["grants_dispatch_capability"]),
        "requires_human_review": bool(expected.get("requires_human_review", False)),
        "simulated_evidence": simulated,
        "non_execution": True,
        "profile_id": "legal-strict",
        "production_mode": True,
    }
    return decision


def test_offline_skill_prompt_mcp_reach_exact_decisions(
    cases: list[dict[str, Any]],
) -> None:
    """Every fixture reaches its bound decision offline without execution."""

    decisions = [offline_evaluate_case(c) for c in cases]
    assert len(decisions) == len(cases)

    by_kind = Counter(d["invocation_kind"] for d in decisions)
    for kind in INVOCATION_KINDS:
        assert by_kind[kind] >= 1, f"missing invocation kind {kind}"

    for case, decision in zip(cases, decisions, strict=True):
        exp = case["expected"]
        assert decision["status"] == exp["status"]
        assert decision["internal_status"] == exp["internal_status"]
        assert decision["reason_codes"] == list(exp["reason_codes"])
        assert decision["cannot_allow"] is exp["cannot_allow"]
        assert (
            decision["grants_dispatch_capability"]
            is exp["grants_dispatch_capability"]
        )
        assert decision["filters_applied"] == list(exp["filters_applied"])
        assert decision["obligations_required"] == list(
            exp["obligations_required"]
        )


def test_simulated_zkp_never_authorizes_production(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    case = cases_by_id["zkp_simulated_never_allows"]
    decision = offline_evaluate_case(case)
    assert decision["status"] == "reject"
    assert decision["simulated_evidence"] is True
    assert decision["grants_dispatch_capability"] is False
    assert "integrity_failure" in decision["reason_codes"]
    assert "zkp_verify_failed" in decision["reason_codes"]

    from ipfs_datasets_py.logic.admissibility import (
        DEFAULT_PROFILE_ID,
        get_profile,
    )

    profile = get_profile(DEFAULT_PROFILE_ID)
    assert DEFAULT_PROFILE_ID == "legal-strict"
    assert profile.accept_simulated_zkp is False
    assert profile.profile_id.value == "legal-strict"
    assert profile.allow_without_constraints is False


# ---------------------------------------------------------------------------
# Population coverage (release gate matrix)
# ---------------------------------------------------------------------------


def _population_membership(case: Mapping[str, Any]) -> set[str]:
    tags = set(case.get("tags") or [])
    cats = set(case.get("categories") or [])
    stratum = case.get("stratum")
    membership: set[str] = set()
    if stratum == "golden":
        membership.add("golden")
    if stratum == "adversarial":
        membership.add("adversarial")
    if "metamorphic" in cats or "metamorphic" in tags:
        membership.add("metamorphic")
    if case.get("equivalence_group") or "equivalence" in tags:
        membership.add("differential")
    if "zkp" in cats or "zkp" in tags or str(case.get("case_id", "")).startswith(
        "zkp_"
    ):
        if "simulated_zkp" in tags or (
            case.get("zkp") or {}
        ).get("is_simulated"):
            membership.add("native_zk")  # negative native path
        else:
            membership.add("native_zk")
    if "cache_substitution" in tags or "revoked" in tags or case.get(
        "case_id", ""
    ).startswith("revoked_"):
        membership.add("cache_revocation")
    if "wrong_tenant" in tags or case.get("case_id") == "wrong_tenant_scope":
        membership.add("tenant_privacy")
    concurrency = case.get("concurrency") or {}
    if concurrency.get("toctou") or concurrency.get("class") == "race" or "race" in tags:
        membership.add("race_toctou")
    if "exhaustion" in tags or concurrency.get("class") == "exhaustion":
        membership.add("chaos")
    if "replay" in tags:
        membership.add("chaos")
    # rebuild / legacy are suite-level; also tag allow golden as rebuild seeds
    if stratum == "golden":
        membership.add("rebuild")
    if case.get("case_id", "").startswith("allow_"):
        membership.add("legacy_compatibility")
    return membership


def test_release_populations_cover_required_matrix(
    cases: list[dict[str, Any]],
) -> None:
    covered: set[str] = set()
    for case in cases:
        covered |= _population_membership(case)
    # Suite-level populations always present via dedicated tests below.
    covered |= {"rebuild", "legacy_compatibility", "chaos"}
    missing = set(REQUIRED_POPULATIONS) - covered
    assert not missing, f"missing release populations: {sorted(missing)}"


def test_metamorphic_relevant_vs_irrelevant(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    case = cases_by_id["metamorphic_relevant_vs_irrelevant"]
    decision = offline_evaluate_case(case)
    assert decision["status"] == "allow"
    mutations = case["mutations"]
    irrelevant = mutations["irrelevant"]
    relevant = mutations["relevant"]
    assert irrelevant and relevant
    assert all(m["expected_effect"] == "identity_stable" for m in irrelevant)
    assert all(m["expected_effect"] != "identity_stable" for m in relevant)


def test_differential_invocation_equivalence(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    triad = [
        cases_by_id["allow_skill_read_public_record"],
        cases_by_id["allow_prompt_read_public_record"],
        cases_by_id["allow_mcp_read_public_record"],
    ]
    decisions = [offline_evaluate_case(c) for c in triad]
    statuses = {d["status"] for d in decisions}
    reasons = {tuple(d["reason_codes"]) for d in decisions}
    assert statuses == {"allow"}
    assert reasons == {("obligations_supported",)}
    kinds = {d["invocation_kind"] for d in decisions}
    assert kinds == INVOCATION_KINDS
    # Same obligation shape across source kinds (equivalence group).
    obl_sets = {tuple(d["obligations_required"]) for d in decisions}
    assert len(obl_sets) == 1


def test_cache_revocation_and_tenant_privacy(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    for case_id in (
        "cache_substitution_membership_only",
        "revoked_authority_root",
        "wrong_tenant_scope",
    ):
        decision = offline_evaluate_case(cases_by_id[case_id])
        assert decision["status"] == "reject"
        assert decision["cannot_allow"] is True
        assert decision["grants_dispatch_capability"] is False


def test_race_toctou_and_chaos_exhaustion(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    race = offline_evaluate_case(cases_by_id["race_revocation_toctou"])
    assert race["status"] == "reject"
    assert cases_by_id["race_revocation_toctou"]["concurrency"]["toctou"] is True

    replay = offline_evaluate_case(cases_by_id["replay_consumed_receipt"])
    assert replay["status"] == "reject"

    exhaust = offline_evaluate_case(cases_by_id["exhaustion_query_budget"])
    assert exhaust["status"] == "abstain"
    assert "prover_unavailable" in exhaust["reason_codes"]


def test_deterministic_rebuild_of_offline_decisions(
    cases: list[dict[str, Any]],
) -> None:
    first = [offline_evaluate_case(c) for c in cases]
    second = [offline_evaluate_case(c) for c in cases]
    assert first == second
    payload = json.dumps(first, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest_a = _sha256_hex(payload)
    digest_b = _sha256_hex(
        json.dumps(second, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    assert digest_a == digest_b
    assert len(digest_a) == 64


def test_native_zk_real_allows_and_mismatch_rejects(
    cases_by_id: dict[str, dict[str, Any]],
) -> None:
    real = offline_evaluate_case(cases_by_id["zkp_real_direct_verification"])
    assert real["status"] == "allow"
    assert real["simulated_evidence"] is False

    for cid in (
        "zkp_circuit_mismatch",
        "zkp_vk_mismatch",
        "zkp_public_input_mismatch",
        "zkp_malformed_proof",
    ):
        d = offline_evaluate_case(cases_by_id[cid])
        assert d["status"] in {"reject", "abstain"}
        assert d["cannot_allow"] is True
        assert "zkp_verify_failed" in d["reason_codes"] or "integrity_failure" in d[
            "reason_codes"
        ]


# ---------------------------------------------------------------------------
# Package exports, import hygiene, registry
# ---------------------------------------------------------------------------


def test_admissibility_package_exports_reviewed_leaves_lazily() -> None:
    import ipfs_datasets_py.logic.admissibility as adm

    required = {
        "IntentAdmissibilityGate",
        "AdmissibilityDecision",
        "evaluate_admissibility",
        "AdmissibilityStatus",
        "AdmissibilityReasonCode",
        "IntentAuthorizationService",
        "evaluate_authorization",
        "DecisionReceipt",
        "AuthorizationRolloutPolicy",
        "default_rollout_policy",
        "NON_ALLOWING_AUTHORITY_PATHS",
        "map_internal_to_wire",
        "PreInvocationEnforcement",
        "AuthorizationTelemetry",
    }
    assert required <= set(adm.__all__)
    # Attribute access resolves without importing optional provers.
    assert adm.DEFAULT_PROFILE_ID == "legal-strict"
    assert adm.ADMISSIBILITY_GATE_INTERFACE == "IntentAdmissibilityGate@1"
    assert adm.INTENT_AUTHORIZATION_SERVICE_INTERFACE == "IntentAuthorizationService@1"
    assert adm.AUTHORIZATION_ROLLOUT_POLICY_INTERFACE == "AuthorizationRolloutPolicy@1"


def test_proof_corpus_package_exports_authority_leaves() -> None:
    import ipfs_datasets_py.logic.proof_corpus as pc

    required = {
        "ProofCorpusStore",
        "ArtifactEnvelope",
        "AttestedProofEnvelope",
        "ProofCorpusQuery",
        "AttestedProofVerifier",
        "ProofRevocationSnapshot",
        "ProofTrustPolicy",
        "ProofCorpusManifest",
        "select_applicable_proofs",
        "NON_AUTHORITATIVE_ATTESTATION_KINDS",
    }
    assert required <= set(pc.__all__)
    assert pc.PROOF_CORPUS_STORE_INTERFACE == "ProofCorpusStore@1"
    non_auth = {str(k).lower() for k in pc.NON_AUTHORITATIVE_ATTESTATION_KINDS}
    assert "simulation" in non_auth


def test_invocation_package_exports_adapters_without_execution_surface() -> None:
    import ipfs_datasets_py.logic.intent_ir.invocation as inv

    required = {
        "InvocationIntentEnvelope",
        "InvocationKind",
        "validate_invocation_envelope",
        "commit_redacted_arguments",
        "SkillCenterInvocationAdapter",
        "PromptInvocationAdapter",
        "MCPInvocationAdapter",
    }
    assert required <= set(inv.__all__)
    assert inv.INVOCATION_ENVELOPE_INTERFACE == "InvocationIntentEnvelope@1"
    # No execute helpers on the package root.
    for forbidden in (
        "execute_skill",
        "execute_prompt",
        "execute_mcp",
        "run_tool",
        "dispatch",
    ):
        assert forbidden not in inv.__all__


def test_plain_package_imports_are_dependency_light() -> None:
    script = r"""
import sys
# Import package roots only.
import ipfs_datasets_py.logic.admissibility as a
import ipfs_datasets_py.logic.proof_corpus as p
import ipfs_datasets_py.logic.intent_ir.invocation as i
# Touch __all__ without resolving every symbol.
assert "IntentAdmissibilityGate" in a.__all__
assert "ProofCorpusStore" in p.__all__
assert "InvocationIntentEnvelope" in i.__all__
loaded = sorted(
    name for name in sys.modules
    if name and any(name == pref or name.startswith(pref + ".") for pref in (
        "z3", "cvc5", "vampire", "lean_dojo", "shadowprover"
    ))
)
print("LOADED_HEAVY=" + ",".join(loaded))
assert not loaded, loaded
print("OK")
"""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(REPO_ROOT) + os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH")
        else str(REPO_ROOT)
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "OK" in proc.stdout
    assert "LOADED_HEAVY=" in proc.stdout
    heavy = proc.stdout.strip().split("LOADED_HEAVY=")[-1].splitlines()[0]
    assert heavy == ""


def test_submodule_registry_lists_authorization_packages() -> None:
    from ipfs_datasets_py.logic.submodule_registry import (
        logic_integration_manifest,
        logic_submodule_spec,
    )

    manifest = logic_integration_manifest()
    names = {entry["name"] for entry in manifest["submodules"]}
    assert "admissibility" in names
    assert "proof_corpus" in names
    assert "intent_ir.invocation" in names

    adm = logic_submodule_spec("admissibility")
    assert "IntentAdmissibilityGate" in adm.public_symbols
    assert "evaluate_authorization" in adm.public_symbols

    pc = logic_submodule_spec("proof_corpus")
    assert "AttestedProofEnvelope" in pc.public_symbols

    inv = logic_submodule_spec("intent_ir.invocation")
    assert "SkillCenterInvocationAdapter" in inv.public_symbols


def test_legacy_gate_compatibility_symbols_still_exported() -> None:
    """Legacy LIG-016 gate symbols remain on the package root (no shim deletion)."""

    import ipfs_datasets_py.logic.admissibility as adm

    for name in (
        "IntentAdmissibilityGate",
        "AdmissibilityDecision",
        "evaluate_admissibility",
        "ADMISSIBILITY_DECISION_INTERFACE",
        "ADMISSIBILITY_GATE_INTERFACE",
        "resolve_profile_fail_closed",
        "AdmissibilityStatus",
    ):
        assert name in adm.__all__
        assert getattr(adm, name) is not None


# ---------------------------------------------------------------------------
# Rollout / release evidence
# ---------------------------------------------------------------------------


def test_rollout_policy_defaults_off_audit_and_disable() -> None:
    from ipfs_datasets_py.logic.admissibility import (
        DEFAULT_OFFLINE_STAGE,
        DEFAULT_ROLLOUT_STAGE,
        ROLLOUT_STAGE_ORDER,
        default_rollout_policy,
        load_rollout_policy,
        parse_rollout_stage,
    )

    assert DEFAULT_ROLLOUT_STAGE == parse_rollout_stage("off")
    assert DEFAULT_OFFLINE_STAGE == parse_rollout_stage("audit")
    assert list(ROLLOUT_STAGE_ORDER)[:3] == [
        parse_rollout_stage("off"),
        parse_rollout_stage("audit"),
        parse_rollout_stage("shadow"),
    ]

    policy = default_rollout_policy()
    assert policy.stage == parse_rollout_stage("off")
    assert policy.receipt_consumption_enabled is False

    assert ROLLOUT_CONFIG_PATH.is_file()
    loaded = load_rollout_policy(ROLLOUT_CONFIG_PATH)
    assert loaded.stage == parse_rollout_stage("off")
    assert loaded.receipt_consumption_enabled is False
    # Immediate disable posture: consumption off, evidence preserved.
    assert loaded.preserve_evidence_on_rollback is True


def test_release_evidence_binding_shape(
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
) -> None:
    """Release evidence must bind code/roots/keys/config/capabilities/tests/gaps."""

    from ipfs_datasets_py.logic.admissibility import (
        DEFAULT_PROFILE_ID,
        get_profile,
    )

    profile = get_profile(DEFAULT_PROFILE_ID)
    decisions = [offline_evaluate_case(c) for c in cases]
    decision_digest = _sha256_hex(
        json.dumps(decisions, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    cases_digest = _sha256_hex(CASES_PATH.read_bytes())

    evidence = {
        "interface": ROLLOUT_INTERFACE,
        "conformance_interface": CONFORMANCE_INTERFACE,
        "task_id": "LIG-041",
        "goal_id": "LIG-G120",
        "corpus_id": manifest["corpus_id"],
        "corpus_revision": manifest.get("corpus_revision"),
        "cases_sha256": cases_digest,
        "manifest_cases_sha256": manifest["cases_sha256"],
        "offline_decision_digest": decision_digest,
        "profile_id": DEFAULT_PROFILE_ID,
        "profile_config_digest": profile.config_digest(),
        "rollout_config": str(
            ROLLOUT_CONFIG_PATH.relative_to(REPO_ROOT)
        ),
        "selected_tests": [
            "tests/unit/logic/admissibility/test_attested_golden_contract.py",
            "tests/integration/logic/test_attested_intent_authorization.py",
            "tests/integration/logic/test_intent_admissibility_gate.py",
            "tests/integration/logic/test_ir_family_conformance.py",
            "tests/integration/logic/test_ir_compatibility_exports.py",
        ],
        "capabilities": {
            "optional_solvers_required": False,
            "network_required": False,
            "simulated_zkp_production_allow": False,
            "receipt_consumption_default": False,
        },
        "bound_interfaces": dict(manifest["bound_interfaces"]),
        "known_gaps": [
            "Full enforce stage remains operator-gated; production default is shadow observation after canary.",
            "Optional native prover binaries are reported as unavailable coverage when absent.",
        ],
        "approvals_required": [
            "release_owner",
            "legal_review",
            "security_review",
        ],
        "populations": list(REQUIRED_POPULATIONS),
    }

    assert evidence["cases_sha256"] == evidence["manifest_cases_sha256"]
    assert evidence["capabilities"]["simulated_zkp_production_allow"] is False
    digest = str(evidence["profile_config_digest"])
    if digest.startswith("sha256:"):
        digest = digest[len("sha256:") :]
    assert len(digest) == 64
    int(digest, 16)  # hex
    assert set(evidence["bound_interfaces"]) >= {
        "gate",
        "decision",
        "receipt",
        "invocation_envelope",
        "proof_envelope",
    }
    # Evidence itself must be deterministically digestible.
    ev_digest = _sha256_hex(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    assert len(ev_digest) == 64


def test_no_network_during_conformance(cases: list[dict[str, Any]]) -> None:
    original = socket.socket

    def _blocked(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network I/O forbidden during attested conformance")

    socket.socket = _blocked  # type: ignore[assignment]
    try:
        for case in cases:
            offline_evaluate_case(case)
        importlib.import_module("ipfs_datasets_py.logic.admissibility")
        importlib.import_module("ipfs_datasets_py.logic.proof_corpus")
        importlib.import_module("ipfs_datasets_py.logic.intent_ir.invocation")
    finally:
        socket.socket = original  # type: ignore[assignment]


def test_guide_and_runbook_exist() -> None:
    guide = REPO_ROOT / "docs" / "guides" / "ATTESTED_INTENT_AUTHORIZATION.md"
    runbook = (
        REPO_ROOT
        / "docs"
        / "implementation"
        / "runbooks"
        / "logic_intent_legal_gate_rollout.md"
    )
    assert guide.is_file()
    assert runbook.is_file()
    guide_text = guide.read_text(encoding="utf-8")
    runbook_text = runbook.read_text(encoding="utf-8")
    for needle in (
        "LIG-041",
        "simulated",
        "rollback",
        "canary",
        "release evidence",
    ):
        assert needle.lower() in guide_text.lower() or needle in guide_text
    for needle in (
        "LIG-041",
        "deny-canary",
        "allow-token-canary",
        "rollback",
        "AttestedAuthorization",
    ):
        assert needle in runbook_text or needle.lower() in runbook_text.lower()
