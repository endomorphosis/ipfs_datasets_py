"""Tests for PolicyPack schema and validator (WS12-01)."""
from __future__ import annotations

import pytest
from reasoner.policy_pack import (
    POLICY_PACK_SCHEMA_VERSION,
    POLICY_PACK_ERROR_CODES,
    PolicyPack,
    PolicyPackValidationError,
    validate_policy_pack,
    build_policy_pack,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _valid_pack(**overrides) -> dict:
    base = {
        "jurisdiction": "US-CA",
        "effective_date": "2024-01-01",
        "priority_policy": {"rule": "highest_specificity"},
        "exception_policy": {"allow_override": True},
        "temporal_policy": {"window_days": 30},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestValidPackPassesValidation
# ---------------------------------------------------------------------------

class TestValidPackPassesValidation:
    def test_valid_pack_is_valid(self):
        # GIVEN a fully populated valid pack
        result = validate_policy_pack(_valid_pack())
        # THEN validation passes with no errors
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["error_codes"] == []

    def test_schema_version_in_result(self):
        # GIVEN a valid pack
        result = validate_policy_pack(_valid_pack())
        # THEN schema_version is explicit in the result
        assert result["schema_version"] == POLICY_PACK_SCHEMA_VERSION
        assert result["schema_version"] == "1.0"

    def test_valid_pack_with_optional_fields(self):
        # GIVEN a pack with optional pack_id and attrs
        pack = _valid_pack(pack_id="pack-001", attrs={"source": "test"})
        result = validate_policy_pack(pack)
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# TestMissingRequiredFields
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    @pytest.mark.parametrize("field_name,error_key", [
        ("jurisdiction", "missing_jurisdiction"),
        ("effective_date", "missing_effective_date"),
        ("priority_policy", "missing_priority_policy"),
        ("exception_policy", "missing_exception_policy"),
        ("temporal_policy", "missing_temporal_policy"),
    ])
    def test_missing_field_emits_correct_error_code(self, field_name, error_key):
        # GIVEN a pack missing one required field
        pack = _valid_pack()
        del pack[field_name]
        # WHEN validated in non-strict mode
        result = validate_policy_pack(pack, strict=False)
        # THEN the correct error code is emitted
        assert result["valid"] is False
        assert POLICY_PACK_ERROR_CODES[error_key] in result["error_codes"]

    def test_null_jurisdiction_emits_error(self):
        # GIVEN jurisdiction is None
        pack = _valid_pack(jurisdiction=None)
        result = validate_policy_pack(pack, strict=False)
        assert POLICY_PACK_ERROR_CODES["missing_jurisdiction"] in result["error_codes"]

    def test_multiple_missing_fields_emit_multiple_codes(self):
        # GIVEN a pack missing jurisdiction and effective_date
        pack = _valid_pack()
        del pack["jurisdiction"]
        del pack["effective_date"]
        result = validate_policy_pack(pack, strict=False)
        assert POLICY_PACK_ERROR_CODES["missing_jurisdiction"] in result["error_codes"]
        assert POLICY_PACK_ERROR_CODES["missing_effective_date"] in result["error_codes"]


# ---------------------------------------------------------------------------
# TestInvalidFieldTypes
# ---------------------------------------------------------------------------

class TestInvalidFieldTypes:
    @pytest.mark.parametrize("field_name,bad_value,error_key", [
        ("priority_policy", "not-a-dict", "invalid_priority_policy_type"),
        ("priority_policy", 42, "invalid_priority_policy_type"),
        ("exception_policy", ["list"], "invalid_exception_policy_type"),
        ("temporal_policy", 3.14, "invalid_temporal_policy_type"),
    ])
    def test_wrong_type_emits_correct_error_code(self, field_name, bad_value, error_key):
        # GIVEN a pack with a field of wrong type
        pack = _valid_pack(**{field_name: bad_value})
        result = validate_policy_pack(pack, strict=False)
        assert result["valid"] is False
        assert POLICY_PACK_ERROR_CODES[error_key] in result["error_codes"]

    def test_invalid_effective_date_format_emits_error(self):
        # GIVEN effective_date in wrong format
        pack = _valid_pack(effective_date="01/01/2024")
        result = validate_policy_pack(pack, strict=False)
        assert POLICY_PACK_ERROR_CODES["invalid_effective_date_format"] in result["error_codes"]

    def test_invalid_effective_date_non_date_string(self):
        # GIVEN effective_date is not a date at all
        pack = _valid_pack(effective_date="not-a-date")
        result = validate_policy_pack(pack, strict=False)
        assert POLICY_PACK_ERROR_CODES["invalid_effective_date_format"] in result["error_codes"]


# ---------------------------------------------------------------------------
# TestStrictMode
# ---------------------------------------------------------------------------

class TestStrictMode:
    def test_strict_mode_raises_on_error(self):
        # GIVEN a pack missing jurisdiction
        pack = _valid_pack()
        del pack["jurisdiction"]
        # WHEN validated in strict mode
        # THEN PolicyPackValidationError is raised
        with pytest.raises(PolicyPackValidationError) as exc_info:
            validate_policy_pack(pack, strict=True)
        err = exc_info.value
        assert POLICY_PACK_ERROR_CODES["missing_jurisdiction"] in err.error_codes
        assert len(err.errors) > 0

    def test_strict_mode_error_has_errors_and_codes_attributes(self):
        # GIVEN a pack with invalid priority_policy type
        pack = _valid_pack(priority_policy="bad")
        with pytest.raises(PolicyPackValidationError) as exc_info:
            validate_policy_pack(pack)
        err = exc_info.value
        assert isinstance(err.errors, list)
        assert isinstance(err.error_codes, list)
        assert len(err.errors) == len(err.error_codes)

    def test_non_strict_mode_returns_errors_without_raising(self):
        # GIVEN a pack missing required fields
        pack = {}
        # WHEN validated in non-strict mode
        result = validate_policy_pack(pack, strict=False)
        # THEN errors are returned, no exception raised
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert len(result["error_codes"]) > 0

    def test_strict_default_raises(self):
        # GIVEN strict=True is the default
        pack = _valid_pack()
        del pack["temporal_policy"]
        with pytest.raises(PolicyPackValidationError):
            validate_policy_pack(pack)


# ---------------------------------------------------------------------------
# TestBuildPolicyPack
# ---------------------------------------------------------------------------

class TestBuildPolicyPack:
    def test_build_creates_correct_dataclass(self):
        # GIVEN a valid pack dict
        pack = _valid_pack(pack_id="p-123", attrs={"env": "prod"})
        # WHEN built
        obj = build_policy_pack(pack)
        # THEN the dataclass has correct fields
        assert isinstance(obj, PolicyPack)
        assert obj.jurisdiction == "US-CA"
        assert obj.effective_date == "2024-01-01"
        assert obj.priority_policy == {"rule": "highest_specificity"}
        assert obj.exception_policy == {"allow_override": True}
        assert obj.temporal_policy == {"window_days": 30}
        assert obj.pack_id == "p-123"
        assert obj.attrs == {"env": "prod"}

    def test_build_sets_schema_version(self):
        # GIVEN a valid pack without explicit schema_version
        obj = build_policy_pack(_valid_pack())
        assert obj.schema_version == POLICY_PACK_SCHEMA_VERSION

    def test_build_raises_on_invalid_pack(self):
        # GIVEN an invalid pack
        with pytest.raises(PolicyPackValidationError):
            build_policy_pack({})

    def test_build_optional_fields_default(self):
        # GIVEN a valid pack with no pack_id or attrs
        obj = build_policy_pack(_valid_pack())
        assert obj.pack_id is None
        assert obj.attrs == {}
