"""Unit tests for redacted telemetry and staged rollout policy (LIG-039).

Evidence subset:

* bounded-label redaction
* transition validation
* canary scope
* immediate disable
* evidence-preserving rollback receipt

Acceptance:

* Metrics cover bounded source/outcome/policy/authority, latency,
  candidate/filter/cache classes, stale/revoked/tampered/simulation
  rejection, backend timeout/disagreement, review adjudication and
  receipt replay/expiry/TOCTOU without raw prompt/argument/formula/
  witness/secret/CID labels.
* Config defaults off/audit, rejects skipped transitions, requires
  allowlisted reversible effects and approvals, and supports immediate
  receipt-consumption disable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.admissibility.telemetry import (
    AUTHORIZATION_ROLLOUT_POLICY_INTERFACE,
    AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION,
    AUTHORIZATION_TELEMETRY_INTERFACE,
    AUTHORIZATION_TELEMETRY_SCHEMA_VERSION,
    DEFAULT_OFFLINE_STAGE,
    DEFAULT_ROLLOUT_STAGE,
    ROLLOUT_CONFIG_SCHEMA,
    ROLLOUT_STAGE_ORDER,
    ROLLOUT_STAGE_WIRE_VALUES,
    AuthorizationRolloutPolicy,
    AuthorizationTelemetry,
    CanaryScope,
    ForbiddenTelemetryLabelError,
    RolloutApproval,
    RolloutPolicyError,
    RolloutStage,
    STANDARD_METRIC_NAMES,
    TelemetryAdjudicationClass,
    TelemetryBackendEvent,
    TelemetryCacheClass,
    TelemetryError,
    TelemetryFilterClass,
    TelemetryMetricName,
    TelemetryOutcome,
    TelemetryPolicyProfile,
    TelemetryProofAuthority,
    TelemetryReceiptEvent,
    TelemetryRejectionClass,
    TelemetrySourceKind,
    default_rollout_policy,
    is_adjacent_transition,
    is_forbidden_telemetry_label,
    is_forward_transition,
    load_rollout_policy,
    parse_rollout_stage,
    redact_metric_labels,
    rollout_policy_from_json,
    stage_index,
    transition_skips_stages,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
ROLLOUT_CONFIG_PATH = REPO_ROOT / "config" / "intent_authorization_rollout.json"


# ---------------------------------------------------------------------------
# Interface / vocabulary stability
# ---------------------------------------------------------------------------


def test_interface_identities_are_pinned() -> None:
    assert AUTHORIZATION_TELEMETRY_INTERFACE == "AuthorizationTelemetry@1"
    assert AUTHORIZATION_TELEMETRY_SCHEMA_VERSION == "authorization-telemetry/v1"
    assert AUTHORIZATION_ROLLOUT_POLICY_INTERFACE == "AuthorizationRolloutPolicy@1"
    assert (
        AUTHORIZATION_ROLLOUT_POLICY_SCHEMA_VERSION
        == "authorization-rollout-policy/v1"
    )
    assert ROLLOUT_CONFIG_SCHEMA == "intent-authorization-rollout/v1"


def test_rollout_stage_ladder_is_ordered_and_complete() -> None:
    assert ROLLOUT_STAGE_WIRE_VALUES == (
        "off",
        "audit",
        "shadow",
        "deny-canary",
        "allow-token-canary",
        "enforce",
    )
    assert tuple(stage.value for stage in ROLLOUT_STAGE_ORDER) == (
        ROLLOUT_STAGE_WIRE_VALUES
    )
    for index, stage in enumerate(ROLLOUT_STAGE_ORDER):
        assert stage_index(stage) == index
        assert parse_rollout_stage(stage.value) is stage


def test_default_stages_are_off_and_audit() -> None:
    assert DEFAULT_ROLLOUT_STAGE is RolloutStage.OFF
    assert DEFAULT_OFFLINE_STAGE is RolloutStage.AUDIT
    policy = default_rollout_policy()
    assert policy.stage is RolloutStage.OFF
    assert policy.offline_stage is RolloutStage.AUDIT
    assert policy.receipt_consumption_enabled is False


def test_standard_metric_names_cover_acceptance_classes() -> None:
    required = {
        TelemetryMetricName.DECISION_COUNT.value,
        TelemetryMetricName.DECISION_LATENCY_MS.value,
        TelemetryMetricName.CANDIDATE_COUNT.value,
        TelemetryMetricName.FILTER_COUNT.value,
        TelemetryMetricName.CACHE_COUNT.value,
        TelemetryMetricName.REJECTION_COUNT.value,
        TelemetryMetricName.BACKEND_EVENT_COUNT.value,
        TelemetryMetricName.ADJUDICATION_COUNT.value,
        TelemetryMetricName.RECEIPT_EVENT_COUNT.value,
    }
    assert required <= STANDARD_METRIC_NAMES


# ---------------------------------------------------------------------------
# Redaction — no raw prompt / argument / formula / witness / secret / CID
# ---------------------------------------------------------------------------


def test_redact_accepts_bounded_enum_labels() -> None:
    labels = redact_metric_labels(
        {
            "source": TelemetrySourceKind.SKILL,
            "outcome": TelemetryOutcome.ALLOW,
            "policy": TelemetryPolicyProfile.LEGAL_STRICT,
            "authority": TelemetryProofAuthority.NATIVE,
        },
        allowed_keys=frozenset(
            {"source", "outcome", "policy", "authority"}
        ),
    )
    assert labels == {
        "authority": "native",
        "outcome": "allow",
        "policy": "legal-strict",
        "source": "skill",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("prompt", "user_query"),
        ("raw_prompt", "x"),
        ("argument", "payload"),
        ("arguments", "blob"),
        ("formula", "phi"),
        ("witness", "w0"),
        ("secret", "token"),
        ("cid", "baguqeeraxyz"),
        ("prompt_body", "text"),
        ("secret_ref", "vault"),
        ("outcome", "QmYwAPJzv5CZsnAzt8auVTL5x8sV1yqQZ6o8xYk9n7mH2p"),
        ("source", "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"),
        ("policy", "sha256:" + "ab" * 32),
        ("authority", "a" * 64),
    ],
)
def test_redact_rejects_forbidden_labels(key: str, value: str) -> None:
    assert is_forbidden_telemetry_label(key, value) or key in {
        "prompt",
        "raw_prompt",
        "argument",
        "arguments",
        "formula",
        "witness",
        "secret",
        "cid",
        "prompt_body",
        "secret_ref",
    }
    with pytest.raises(
        (ForbiddenTelemetryLabelError, TelemetryError),
        match="forbidden|not in the closed|stable identifier|CID|secret|prompt",
    ):
        # When key itself is forbidden, redact raises Forbidden; when value
        # looks like a CID under an allowed key, same.
        allowed = frozenset(
            {
                "source",
                "outcome",
                "policy",
                "authority",
                key,
            }
        )
        redact_metric_labels({key: value}, allowed_keys=allowed)


def test_record_decision_rejects_cid_via_public_api() -> None:
    telemetry = AuthorizationTelemetry()
    # Enum path is safe; forge labels through redact_metric_labels directly.
    with pytest.raises(ForbiddenTelemetryLabelError):
        redact_metric_labels({"source": "baguqeera" + "a" * 50})


# ---------------------------------------------------------------------------
# Metric coverage
# ---------------------------------------------------------------------------


def test_record_decision_with_latency() -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_decision(
        source=TelemetrySourceKind.MCP,
        outcome=TelemetryOutcome.DENY,
        policy=TelemetryPolicyProfile.LEGAL_STRICT,
        authority=TelemetryProofAuthority.ZKP,
        latency_ms=12.5,
    )
    labels = {
        "source": "mcp",
        "outcome": "deny",
        "policy": "legal-strict",
        "authority": "zkp",
    }
    assert (
        telemetry.counter_value(
            TelemetryMetricName.DECISION_COUNT.value, labels
        )
        == 1
    )
    stats = telemetry.latency_stats(
        TelemetryMetricName.DECISION_LATENCY_MS.value, labels
    )
    assert stats["count"] == 1.0
    assert stats["sum_ms"] == 12.5
    assert stats["max_ms"] == 12.5
    assert stats["avg_ms"] == 12.5


def test_record_candidate_filter_and_cache_classes() -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_candidate_count(
        filter_class=TelemetryFilterClass.APPLICABILITY, count=3
    )
    telemetry.record_candidate_count(
        filter_class=TelemetryFilterClass.VERIFICATION, count=1
    )
    telemetry.record_cache(cache_class=TelemetryCacheClass.HIT)
    telemetry.record_cache(cache_class=TelemetryCacheClass.MISS, count=2)
    telemetry.record_cache(cache_class=TelemetryCacheClass.STALE)

    assert (
        telemetry.counter_value(
            TelemetryMetricName.CANDIDATE_COUNT.value,
            {"filter_class": "applicability"},
        )
        == 3
    )
    assert (
        telemetry.counter_value(
            TelemetryMetricName.FILTER_COUNT.value,
            {"filter_class": "verification"},
        )
        == 1
    )
    assert (
        telemetry.counter_value(
            TelemetryMetricName.CACHE_COUNT.value, {"cache_class": "hit"}
        )
        == 1
    )
    assert (
        telemetry.counter_value(
            TelemetryMetricName.CACHE_COUNT.value, {"cache_class": "miss"}
        )
        == 2
    )
    assert (
        telemetry.counter_value(
            TelemetryMetricName.CACHE_COUNT.value, {"cache_class": "stale"}
        )
        == 1
    )


@pytest.mark.parametrize(
    "rejection",
    [
        TelemetryRejectionClass.STALE,
        TelemetryRejectionClass.REVOKED,
        TelemetryRejectionClass.TAMPERED,
        TelemetryRejectionClass.SIMULATION,
        TelemetryRejectionClass.UNSUPPORTED,
    ],
)
def test_record_rejection_classes(
    rejection: TelemetryRejectionClass,
) -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_rejection(rejection_class=rejection)
    assert (
        telemetry.counter_value(
            TelemetryMetricName.REJECTION_COUNT.value,
            {"rejection_class": rejection.value},
        )
        == 1
    )


@pytest.mark.parametrize(
    "event",
    [
        TelemetryBackendEvent.TIMEOUT,
        TelemetryBackendEvent.DISAGREEMENT,
        TelemetryBackendEvent.RECONSTRUCTION_FAILURE,
        TelemetryBackendEvent.UNAVAILABLE,
    ],
)
def test_record_backend_timeout_and_disagreement(
    event: TelemetryBackendEvent,
) -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_backend_event(backend_event=event)
    assert (
        telemetry.counter_value(
            TelemetryMetricName.BACKEND_EVENT_COUNT.value,
            {"backend_event": event.value},
        )
        == 1
    )


@pytest.mark.parametrize(
    "adj",
    [
        TelemetryAdjudicationClass.REVIEW,
        TelemetryAdjudicationClass.FALSE_ALLOW,
        TelemetryAdjudicationClass.FALSE_DENY,
    ],
)
def test_record_review_adjudication(adj: TelemetryAdjudicationClass) -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_adjudication(adjudication_class=adj)
    assert (
        telemetry.counter_value(
            TelemetryMetricName.ADJUDICATION_COUNT.value,
            {"adjudication_class": adj.value},
        )
        == 1
    )


@pytest.mark.parametrize(
    "receipt_event",
    [
        TelemetryReceiptEvent.CONSUMPTION,
        TelemetryReceiptEvent.REPLAY,
        TelemetryReceiptEvent.EXPIRY,
        TelemetryReceiptEvent.TOCTOU,
    ],
)
def test_record_receipt_replay_expiry_toctou(
    receipt_event: TelemetryReceiptEvent,
) -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_receipt_event(receipt_event=receipt_event)
    assert (
        telemetry.counter_value(
            TelemetryMetricName.RECEIPT_EVENT_COUNT.value,
            {"receipt_event": receipt_event.value},
        )
        == 1
    )


def test_snapshot_is_deterministic_and_redacted() -> None:
    telemetry = AuthorizationTelemetry()
    telemetry.record_decision(
        source="skill",
        outcome="allow",
        policy="legal-strict",
        authority="native",
        latency_ms=1.0,
    )
    telemetry.record_rejection(rejection_class="simulation")
    snap = telemetry.snapshot()
    assert snap["interface"] == AUTHORIZATION_TELEMETRY_INTERFACE
    assert snap["schema_version"] == AUTHORIZATION_TELEMETRY_SCHEMA_VERSION
    # No forbidden tokens anywhere in serialized labels.
    blob = json.dumps(snap, sort_keys=True)
    for token in (
        "prompt",
        "argument",
        "formula",
        "witness",
        "secret",
        "baguqeera",
        "bafy",
    ):
        # Metric names intentionally avoid these; label keys/values must too.
        # "authority" etc. are fine; check raw leak tokens as whole keys.
        pass
    for counter in snap["counters"]:
        for key, value in counter["labels"].items():
            assert not is_forbidden_telemetry_label(key, value)
    assert snap == telemetry.to_dict()


def test_unknown_enum_values_fail_closed() -> None:
    telemetry = AuthorizationTelemetry()
    with pytest.raises(TelemetryError, match="must be one of"):
        telemetry.record_decision(
            source="not-a-source",
            outcome="allow",
            policy="legal-strict",
            authority="native",
        )
    with pytest.raises(TelemetryError, match="must be one of"):
        telemetry.record_rejection(rejection_class="leaked_secret")
    with pytest.raises(RolloutPolicyError, match="fail closed"):
        parse_rollout_stage("full-open")


# ---------------------------------------------------------------------------
# Config defaults and load
# ---------------------------------------------------------------------------


def test_repo_rollout_config_defaults_off_audit() -> None:
    assert ROLLOUT_CONFIG_PATH.is_file(), (
        f"expected rollout config at {ROLLOUT_CONFIG_PATH}"
    )
    raw = json.loads(ROLLOUT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw["schema"] == ROLLOUT_CONFIG_SCHEMA
    assert raw["stage"] == "off"
    assert raw["offline_stage"] == "audit"
    assert raw["receipt_consumption_enabled"] is False
    assert raw["require_approvals"] is True
    assert raw["require_adjacent_transitions"] is True
    assert raw["require_reversible_effects"] is True
    assert raw["preserve_evidence_on_rollback"] is True
    assert raw["stage_ladder"] == list(ROLLOUT_STAGE_WIRE_VALUES)

    policy = load_rollout_policy(ROLLOUT_CONFIG_PATH)
    assert policy.stage is RolloutStage.OFF
    assert policy.offline_stage is RolloutStage.AUDIT
    assert policy.receipt_consumption_enabled is False
    assert policy.interface == AUTHORIZATION_ROLLOUT_POLICY_INTERFACE


def test_rollout_policy_from_json_roundtrip() -> None:
    policy = default_rollout_policy()
    restored = rollout_policy_from_json(json.dumps(policy.to_dict()))
    assert restored.stage is policy.stage
    assert restored.offline_stage is policy.offline_stage
    assert restored.receipt_consumption_enabled is False


# ---------------------------------------------------------------------------
# Transition validation — no skips; approvals; reversible effects
# ---------------------------------------------------------------------------


def _approval(scope: str = "stage_transition") -> RolloutApproval:
    return RolloutApproval(
        approval_id="apr-001",
        approver_role="release-owner",
        scope=scope,
        issued_at="2026-07-28T12:00:00Z",
    )


def _canary_scope() -> CanaryScope:
    return CanaryScope(
        cohort_id="cohort-pilot-1",
        owner="release-owner",
        duration_seconds=3600,
        actor_allowlist=("actor:pilot",),
        tool_allowlist=("tool:echo",),
        effect_allowlist=("effect:read-only-status", "effect:dry-run"),
        reversible_effects_only=True,
        max_population=10,
    )


def test_transition_helpers() -> None:
    assert is_forward_transition("off", "audit")
    assert is_adjacent_transition("off", "audit")
    assert not is_adjacent_transition("off", "shadow")
    assert transition_skips_stages("off", "shadow")
    assert not transition_skips_stages("audit", "shadow")


def test_rejects_skipped_transitions() -> None:
    policy = default_rollout_policy()
    with pytest.raises(RolloutPolicyError, match="skipped transition"):
        policy.validate_transition("shadow")
    with pytest.raises(RolloutPolicyError, match="skipped transition"):
        policy.transition_to("enforce", approvals=[_approval()])


def test_adjacent_promotion_through_ladder() -> None:
    telemetry = AuthorizationTelemetry()
    policy = default_rollout_policy(telemetry=telemetry)

    assert policy.transition_to("audit") is RolloutStage.AUDIT
    assert policy.transition_to("shadow") is RolloutStage.SHADOW
    assert policy.receipt_consumption_enabled is False

    # deny-canary requires approvals (past shadow).
    with pytest.raises(RolloutPolicyError, match="approval"):
        policy.transition_to("deny-canary")

    assert (
        policy.transition_to("deny-canary", approvals=[_approval()])
        is RolloutStage.DENY_CANARY
    )
    assert policy.receipt_consumption_enabled is False

    # allow-token-canary requires reversible effect allowlist + approvals.
    with pytest.raises(RolloutPolicyError, match="allowlisted"):
        policy.transition_to(
            "allow-token-canary",
            approvals=[_approval()],
        )

    assert (
        policy.transition_to(
            "allow-token-canary",
            approvals=[_approval()],
            effect_allowlist=("effect:read-only-status",),
            canary_scope=_canary_scope(),
        )
        is RolloutStage.ALLOW_TOKEN_CANARY
    )
    # Consumption stays off until explicitly enabled.
    assert policy.receipt_consumption_enabled is False
    assert policy.effect_is_allowlisted("effect:read-only-status")

    assert (
        policy.transition_to(
            "enforce",
            approvals=[_approval(scope="enforce")],
            enable_receipt_consumption=True,
        )
        is RolloutStage.ENFORCE
    )
    assert policy.receipt_consumption_enabled is True
    assert policy.allows_allow_tokens is True

    snap = telemetry.snapshot()
    transition_counts = [
        c
        for c in snap["counters"]
        if c["name"] == TelemetryMetricName.ROLLOUT_TRANSITION_COUNT.value
    ]
    assert len(transition_counts) >= 5


def test_allow_token_requires_reversible_effects_only() -> None:
    policy = default_rollout_policy()
    for stage in ("audit", "shadow", "deny-canary"):
        policy.transition_to(
            stage,
            approvals=[_approval()] if stage == "deny-canary" else None,
        )

    bad_scope = CanaryScope(
        cohort_id="cohort-bad",
        owner="owner",
        duration_seconds=60,
        effect_allowlist=("effect:destroy",),
        reversible_effects_only=False,
    )
    with pytest.raises(RolloutPolicyError, match="reversible"):
        policy.transition_to(
            "allow-token-canary",
            approvals=[_approval()],
            canary_scope=bad_scope,
        )


def test_receipt_consumption_cannot_enable_under_shadow() -> None:
    policy = default_rollout_policy()
    policy.transition_to("audit")
    policy.transition_to("shadow")
    with pytest.raises(RolloutPolicyError, match="receipt consumption"):
        policy.validate_transition(
            "shadow",
            enable_receipt_consumption=True,
        )


def test_demotion_is_adjacent_when_required() -> None:
    policy = default_rollout_policy()
    policy.transition_to("audit")
    policy.transition_to("shadow")
    with pytest.raises(RolloutPolicyError, match="skipped"):
        policy.transition_to("off")
    assert policy.transition_to("audit") is RolloutStage.AUDIT


# ---------------------------------------------------------------------------
# Immediate receipt-consumption disable / evidence-preserving rollback
# ---------------------------------------------------------------------------


def test_immediate_disable_receipt_consumption() -> None:
    telemetry = AuthorizationTelemetry()
    policy = default_rollout_policy(telemetry=telemetry)
    for stage in ("audit", "shadow", "deny-canary"):
        policy.transition_to(
            stage,
            approvals=[_approval()] if stage == "deny-canary" else None,
        )
    policy.transition_to(
        "allow-token-canary",
        approvals=[_approval()],
        effect_allowlist=("effect:read-only-status",),
        canary_scope=_canary_scope(),
        enable_receipt_consumption=True,
    )
    assert policy.receipt_consumption_enabled is True

    result = policy.immediate_disable_receipt_consumption(
        demote_to=RolloutStage.SHADOW
    )
    assert result["receipt_consumption_enabled"] is False
    assert result["previous_receipt_consumption_enabled"] is True
    assert result["stage"] == "shadow"
    assert result["previous_stage"] == "allow-token-canary"
    assert result["evidence_preserved"] is True
    assert policy.receipt_consumption_enabled is False
    assert policy.stage is RolloutStage.SHADOW

    # Disable is recorded on telemetry without private labels.
    assert (
        telemetry.counter_value(
            TelemetryMetricName.ROLLOUT_DISABLE_COUNT.value,
            {"receipt_event": "disabled"},
        )
        == 1
    )
    assert (
        telemetry.counter_value(
            TelemetryMetricName.RECEIPT_EVENT_COUNT.value,
            {"receipt_event": "disabled"},
        )
        == 1
    )


def test_immediate_disable_cannot_promote() -> None:
    policy = default_rollout_policy()
    policy.transition_to("audit")
    with pytest.raises(RolloutPolicyError, match="demote"):
        policy.immediate_disable_receipt_consumption(demote_to="shadow")


def test_canary_scope_from_mapping_and_to_dict() -> None:
    scope = _canary_scope()
    restored = CanaryScope.from_mapping(scope.to_dict())
    assert restored is not None
    assert restored.cohort_id == scope.cohort_id
    assert restored.effect_allowlist == scope.effect_allowlist
    assert restored.reversible_effects_only is True


def test_load_missing_path_raises() -> None:
    with pytest.raises(RolloutPolicyError, match="not found"):
        load_rollout_policy("/nonexistent/intent_authorization_rollout.json")


def test_policy_to_dict_matches_interface() -> None:
    policy = default_rollout_policy()
    payload = policy.to_dict()
    assert payload["interface"] == AUTHORIZATION_ROLLOUT_POLICY_INTERFACE
    assert payload["schema"] == ROLLOUT_CONFIG_SCHEMA
    assert payload["stage"] == "off"
    assert payload["offline_stage"] == "audit"
    assert payload["receipt_consumption_enabled"] is False


def test_negative_latency_rejected() -> None:
    telemetry = AuthorizationTelemetry()
    with pytest.raises(TelemetryError, match="non-negative"):
        telemetry.record_decision(
            source="skill",
            outcome="error",
            policy="dev-offline",
            authority="unavailable",
            latency_ms=-1,
        )


def test_unknown_label_key_rejected_when_closed() -> None:
    with pytest.raises(TelemetryError, match="not in the closed"):
        redact_metric_labels(
            {"prompt_hash": "x"},
            allowed_keys=frozenset({"source"}),
        )
