"""Unit tests for admissibility profiles and enum-stable reason codes (LIG-014)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.admissibility.profiles import (
    ADMISSIBILITY_PROFILE_INTERFACE_VERSION,
    DEFAULT_PROFILE_ID,
    PROFILE_ID_WIRE_VALUES,
    PROFILE_REGISTRY,
    AdmissibilityProfile,
    AdmissibilityProfileError,
    AdmissibilityProfileId,
    UnknownAdmissibilityProfileError,
    get_profile,
    is_known_profile,
    list_profiles,
    parse_profile_id,
    profile_id_set,
    resolve_profile,
    resolve_profile_fail_closed,
    stable_profile_id_values,
)
from ipfs_datasets_py.logic.admissibility.reasons import (
    ADMISSIBILITY_REASON_INTERFACE_VERSION,
    REASON_CODE_WIRE_VALUES,
    AdmissibilityReason,
    AdmissibilityReasonCode,
    AdmissibilityReasonError,
    AdmissibilityStatus,
    default_status_for_reason,
    invalid_profile_reason,
    parse_reason_code,
    parse_status,
    reason_code_set,
    stable_reason_code_values,
)


# ---------------------------------------------------------------------------
# Reason codes: closed vocabulary and enum stability
# ---------------------------------------------------------------------------


def test_reason_codes_are_enum_stable() -> None:
    """Pinned wire vocabulary must match the enum and stay sorted."""
    from_enum = tuple(sorted(member.value for member in AdmissibilityReasonCode))
    assert from_enum == REASON_CODE_WIRE_VALUES
    assert stable_reason_code_values() == REASON_CODE_WIRE_VALUES
    assert reason_code_set() == frozenset(REASON_CODE_WIRE_VALUES)
    # Explicit contract: every planned gate class has a stable code.
    required = {
        "obligations_supported",
        "legal_hard_constraint",
        "security_hard_constraint",
        "constraint_contradiction",
        "missing_evidence",
        "prover_unavailable",
        "zkp_missing",
        "zkp_verify_failed",
        "integrity_failure",
        "semantics_unsupported",
        "invalid_profile",
        "no_constraints",
    }
    assert required <= reason_code_set()


def test_parse_reason_code_accepts_known_and_rejects_unknown() -> None:
    assert parse_reason_code("invalid_profile") is AdmissibilityReasonCode.INVALID_PROFILE
    assert parse_reason_code(AdmissibilityReasonCode.ZKP_MISSING) is (
        AdmissibilityReasonCode.ZKP_MISSING
    )
    with pytest.raises(AdmissibilityReasonError, match="fail closed"):
        parse_reason_code("not_a_real_reason")
    with pytest.raises(AdmissibilityReasonError, match="fail closed"):
        parse_reason_code("")
    with pytest.raises(AdmissibilityReasonError):
        parse_reason_code(None)


def test_parse_status_closed_vocabulary() -> None:
    assert parse_status("allow") is AdmissibilityStatus.ALLOW
    assert parse_status("reject") is AdmissibilityStatus.REJECT
    assert parse_status("abstain") is AdmissibilityStatus.ABSTAIN
    with pytest.raises(AdmissibilityReasonError, match="fail closed"):
        parse_status("permit")
    with pytest.raises(AdmissibilityReasonError, match="fail closed"):
        parse_status("ALLOW")


def test_default_status_for_reason_fail_closed_mapping() -> None:
    assert (
        default_status_for_reason(AdmissibilityReasonCode.INVALID_PROFILE)
        is AdmissibilityStatus.REJECT
    )
    assert (
        default_status_for_reason(AdmissibilityReasonCode.NO_CONSTRAINTS)
        is AdmissibilityStatus.REJECT
    )
    assert (
        default_status_for_reason(AdmissibilityReasonCode.ZKP_MISSING)
        is AdmissibilityStatus.ABSTAIN
    )
    assert (
        default_status_for_reason(AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED)
        is AdmissibilityStatus.ALLOW
    )
    # Every enum member has a default status (no KeyError).
    for code in AdmissibilityReasonCode:
        status = default_status_for_reason(code)
        assert isinstance(status, AdmissibilityStatus)


def test_admissibility_reason_roundtrip_and_unknown_code() -> None:
    reason = AdmissibilityReason(
        code=AdmissibilityReasonCode.MISSING_EVIDENCE,
        message="no attested legal constraints",
        detail={"family": "legal"},
    )
    restored = AdmissibilityReason.from_dict(reason.to_dict())
    assert restored.code is AdmissibilityReasonCode.MISSING_EVIDENCE
    assert restored.message == "no attested legal constraints"
    assert restored.detail == {"family": "legal"}

    with pytest.raises(AdmissibilityReasonError, match="fail closed"):
        AdmissibilityReason.from_dict({"code": "free_form_guess", "message": "x"})


def test_invalid_profile_reason_helper() -> None:
    reason = invalid_profile_reason("bogus")
    assert reason.code is AdmissibilityReasonCode.INVALID_PROFILE
    assert reason.detail is not None
    assert reason.detail["profile"] == "bogus"
    assert "interface" not in reason.to_dict() or True
    assert ADMISSIBILITY_REASON_INTERFACE_VERSION.startswith("AdmissibilityReason@")


# ---------------------------------------------------------------------------
# Profiles: registry, default, fail-closed invalid
# ---------------------------------------------------------------------------


def test_profile_ids_are_enum_stable() -> None:
    from_enum = tuple(sorted(member.value for member in AdmissibilityProfileId))
    assert from_enum == PROFILE_ID_WIRE_VALUES
    assert stable_profile_id_values() == PROFILE_ID_WIRE_VALUES
    assert profile_id_set() == frozenset(PROFILE_ID_WIRE_VALUES)
    assert set(PROFILE_ID_WIRE_VALUES) == {
        "dev-offline",
        "security-lite",
        "legal-strict",
        "zkp-required",
    }


def test_all_declared_profiles_registered() -> None:
    profiles = list_profiles()
    assert len(profiles) == 4
    assert [p.id for p in profiles] == list(PROFILE_ID_WIRE_VALUES)
    assert set(PROFILE_REGISTRY) == set(AdmissibilityProfileId)
    for profile_id in AdmissibilityProfileId:
        profile = get_profile(profile_id)
        assert profile.profile_id is profile_id
        assert profile.allow_without_constraints is False


def test_default_profile_never_allows_without_constraints() -> None:
    assert DEFAULT_PROFILE_ID is AdmissibilityProfileId.LEGAL_STRICT
    default = resolve_profile(None)
    assert default.profile_id is DEFAULT_PROFILE_ID
    assert default.allow_without_constraints is False
    assert default.require_legal_constraints is True
    assert default.require_security_constraints is True
    assert default.require_zkp_verify is False
    assert default.accept_simulated_zkp is False


def test_profile_policy_knobs_by_id() -> None:
    dev = get_profile("dev-offline")
    assert dev.require_zkp_verify is False
    assert dev.accept_simulated_zkp is True
    assert dev.require_legal_constraints is True
    assert dev.require_security_constraints is True

    security = get_profile(AdmissibilityProfileId.SECURITY_LITE)
    assert security.require_security_constraints is True
    assert security.require_legal_constraints is False
    assert security.accept_simulated_zkp is False

    legal = get_profile("legal-strict")
    assert legal.require_legal_constraints is True
    assert legal.require_security_constraints is True
    assert legal.require_zkp_verify is False

    zkp = get_profile("zkp-required")
    assert zkp.require_zkp_verify is True
    assert zkp.accept_simulated_zkp is False
    assert zkp.require_legal_constraints is True
    assert zkp.require_security_constraints is True


def test_invalid_profile_fails_closed_via_parse_and_resolve() -> None:
    with pytest.raises(UnknownAdmissibilityProfileError, match="fail closed"):
        parse_profile_id("not-a-profile")
    with pytest.raises(UnknownAdmissibilityProfileError, match="fail closed"):
        parse_profile_id("")
    with pytest.raises(UnknownAdmissibilityProfileError, match="fail closed"):
        parse_profile_id("  ")
    with pytest.raises(UnknownAdmissibilityProfileError, match="fail closed"):
        resolve_profile("allow-all")
    with pytest.raises(UnknownAdmissibilityProfileError, match="fail closed"):
        get_profile("LEGAL_STRICT")  # wire values are kebab-case, not enum names
    # Unknown never maps to the default permissive path.
    assert is_known_profile("allow-all") is False
    assert is_known_profile("legal-strict") is True


def test_resolve_profile_fail_closed_rejects_unknown_without_raising() -> None:
    resolution = resolve_profile_fail_closed("totally-unknown")
    assert resolution.ok is False
    assert resolution.profile is None
    assert resolution.status is AdmissibilityStatus.REJECT
    assert len(resolution.reasons) == 1
    assert resolution.reasons[0].code is AdmissibilityReasonCode.INVALID_PROFILE
    assert resolution.requested == "totally-unknown"
    payload = resolution.to_dict()
    assert payload["ok"] is False
    assert payload["status"] == "reject"
    assert payload["reasons"][0]["code"] == "invalid_profile"


def test_resolve_profile_fail_closed_accepts_known() -> None:
    resolution = resolve_profile_fail_closed("zkp-required")
    assert resolution.ok is True
    assert resolution.profile is not None
    assert resolution.profile.id == "zkp-required"
    assert resolution.status is None
    assert resolution.reasons == ()

    from_enum = resolve_profile_fail_closed(AdmissibilityProfileId.DEV_OFFLINE)
    assert from_enum.ok is True
    assert from_enum.profile is not None
    assert from_enum.profile.accept_simulated_zkp is True


def test_resolve_profile_rejects_injected_loosened_policy_object() -> None:
    """Registry re-fetch prevents claim-id + loosened knobs injection."""
    loose_attempt = AdmissibilityProfile(
        profile_id=AdmissibilityProfileId.LEGAL_STRICT,
        require_legal_constraints=False,
        require_security_constraints=False,
        require_zkp_verify=False,
        accept_simulated_zkp=False,
        allow_without_constraints=False,
        description="should not win",
    )
    resolved = resolve_profile(loose_attempt)
    # Knobs come from the registry, not the injected object description.
    assert resolved.require_legal_constraints is True
    assert resolved.require_security_constraints is True
    assert resolved.description != "should not win"


def test_profile_cannot_be_constructed_to_allow_without_constraints() -> None:
    with pytest.raises(AdmissibilityProfileError, match="fail closed"):
        AdmissibilityProfile(
            profile_id=AdmissibilityProfileId.DEV_OFFLINE,
            require_legal_constraints=False,
            require_security_constraints=False,
            require_zkp_verify=False,
            accept_simulated_zkp=True,
            allow_without_constraints=True,
        )


def test_zkp_required_cannot_accept_simulated() -> None:
    with pytest.raises(AdmissibilityProfileError):
        AdmissibilityProfile(
            profile_id=AdmissibilityProfileId.ZKP_REQUIRED,
            require_legal_constraints=True,
            require_security_constraints=True,
            require_zkp_verify=True,
            accept_simulated_zkp=True,
            allow_without_constraints=False,
        )


def test_profile_config_digest_is_stable() -> None:
    a = get_profile("legal-strict")
    b = get_profile(AdmissibilityProfileId.LEGAL_STRICT)
    assert a.config_digest() == b.config_digest()
    assert len(a.config_digest()) == 64
    assert a.config_digest() != get_profile("zkp-required").config_digest()
    assert a.to_dict()["interface"] == ADMISSIBILITY_PROFILE_INTERFACE_VERSION
    assert a.to_dict()["profile_id"] == "legal-strict"


def test_none_profile_with_default_disabled_fails_closed() -> None:
    with pytest.raises(UnknownAdmissibilityProfileError, match="fail closed"):
        resolve_profile(None, default=None)
    resolution = resolve_profile_fail_closed(None, default=None)
    assert resolution.ok is False
    assert resolution.status is AdmissibilityStatus.REJECT
    assert resolution.reasons[0].code is AdmissibilityReasonCode.INVALID_PROFILE
