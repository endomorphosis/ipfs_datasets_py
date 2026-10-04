"""
Tests for the logic module input validators.

Tests validate_formula_string, validate_axiom_list,
validate_logic_system, validate_timeout_ms, and validate_format.
"""

import pytest

from ipfs_datasets_py.logic.common.validators import (
    validate_formula_string,
    validate_axiom_list,
    validate_logic_system,
    validate_timeout_ms,
    validate_format,
    MAX_FORMULA_LENGTH,
    MAX_AXIOM_COUNT,
    MAX_TIMEOUT_MS,
    MIN_TIMEOUT_MS,
)
from ipfs_datasets_py.logic.common.errors import ValidationError


class TestValidateFormulaString:
    """Tests for validate_formula_string."""

    def test_valid_formula_passes(self):
        """
        GIVEN a valid formula string
        WHEN validating
        THEN should not raise.
        """
        validate_formula_string("P ∧ Q → R")

    def test_empty_formula_raises(self):
        """
        GIVEN an empty string
        WHEN validating (allow_empty=False)
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_formula_string("")

    def test_whitespace_only_raises(self):
        """
        GIVEN a whitespace-only string
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_formula_string("   ")

    def test_empty_allowed_when_flag_set(self):
        """
        GIVEN allow_empty=True
        WHEN validating empty string
        THEN should not raise.
        """
        validate_formula_string("", allow_empty=True)

    def test_non_string_raises(self):
        """
        GIVEN a non-string input
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must be a string"):
            validate_formula_string(123)  # type: ignore

    def test_too_long_raises(self):
        """
        GIVEN a string exceeding max_length
        WHEN validating
        THEN should raise ValidationError.
        """
        long_formula = "P" * (MAX_FORMULA_LENGTH + 1)
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_formula_string(long_formula)

    def test_custom_max_length(self):
        """
        GIVEN a custom max_length of 10
        WHEN validating a string of length 11
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_formula_string("P" * 11, max_length=10)

    def test_injection_pattern_raises(self):
        """
        GIVEN a string containing __import__
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="unsafe content"):
            validate_formula_string("P ∧ __import__('os')")

    def test_eval_pattern_raises(self):
        """
        GIVEN a string containing eval(
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="unsafe content"):
            validate_formula_string("eval(formula)")

    def test_custom_field_name_in_error(self):
        """
        GIVEN field_name='goal'
        WHEN validating an empty string
        THEN error message should reference 'goal'.
        """
        with pytest.raises(ValidationError, match="'goal'"):
            validate_formula_string("", field_name="goal")

    def test_unicode_formula_passes(self):
        """
        GIVEN a formula with unicode logical symbols
        WHEN validating
        THEN should not raise.
        """
        validate_formula_string("∀x.(P(x) → Q(x)) ∧ ∃y.(R(y) ↔ S(y))")


class TestValidateAxiomList:
    """Tests for validate_axiom_list."""

    def test_valid_axiom_list_passes(self):
        """
        GIVEN a valid list of axiom strings
        WHEN validating
        THEN should not raise.
        """
        validate_axiom_list(["P → Q", "Q → R", "P"])

    def test_empty_list_passes(self):
        """
        GIVEN an empty axiom list
        WHEN validating
        THEN should not raise.
        """
        validate_axiom_list([])

    def test_non_list_raises(self):
        """
        GIVEN a non-list input
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must be a list"):
            validate_axiom_list("not a list")  # type: ignore

    def test_too_many_axioms_raises(self):
        """
        GIVEN a list exceeding max_count
        WHEN validating
        THEN should raise ValidationError.
        """
        axioms = ["P"] * (MAX_AXIOM_COUNT + 1)
        with pytest.raises(ValidationError, match="exceeds maximum"):
            validate_axiom_list(axioms)

    def test_invalid_axiom_in_list_raises(self):
        """
        GIVEN a list with an empty axiom
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_axiom_list(["P → Q", ""])


class TestValidateLogicSystem:
    """Tests for validate_logic_system."""

    def test_tdfol_passes(self):
        """
        GIVEN 'tdfol' as logic
        WHEN validating
        THEN should not raise.
        """
        validate_logic_system("tdfol")

    def test_cec_passes(self):
        """
        GIVEN 'cec' as logic
        WHEN validating
        THEN should not raise.
        """
        validate_logic_system("cec")

    def test_fol_passes(self):
        """
        GIVEN 'fol' as logic
        WHEN validating
        THEN should not raise.
        """
        validate_logic_system("fol")

    def test_invalid_logic_raises(self):
        """
        GIVEN an unsupported logic name
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="Unsupported logic system"):
            validate_logic_system("quantum_logic_v9")

    def test_non_string_raises(self):
        """
        GIVEN a non-string logic identifier
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must be a string"):
            validate_logic_system(42)  # type: ignore

    def test_custom_supported_set(self):
        """
        GIVEN a custom supported set {'mylogic'}
        WHEN validating 'mylogic'
        THEN should not raise.
        """
        validate_logic_system("mylogic", supported={"mylogic"})

    def test_custom_supported_set_rejects_standard(self):
        """
        GIVEN a custom supported set {'mylogic'}
        WHEN validating 'tdfol'
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError):
            validate_logic_system("tdfol", supported={"mylogic"})


class TestValidateTimeoutMs:
    """Tests for validate_timeout_ms."""

    def test_valid_timeout_passes(self):
        """
        GIVEN a timeout within valid range
        WHEN validating
        THEN should not raise.
        """
        validate_timeout_ms(5000)

    def test_minimum_timeout_passes(self):
        """
        GIVEN the minimum allowed timeout
        WHEN validating
        THEN should not raise.
        """
        validate_timeout_ms(MIN_TIMEOUT_MS)

    def test_maximum_timeout_passes(self):
        """
        GIVEN the maximum allowed timeout
        WHEN validating
        THEN should not raise.
        """
        validate_timeout_ms(MAX_TIMEOUT_MS)

    def test_below_minimum_raises(self):
        """
        GIVEN a timeout below minimum
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="≥"):
            validate_timeout_ms(MIN_TIMEOUT_MS - 1)

    def test_above_maximum_raises(self):
        """
        GIVEN a timeout above maximum
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="≤"):
            validate_timeout_ms(MAX_TIMEOUT_MS + 1)

    def test_non_integer_raises(self):
        """
        GIVEN a non-integer timeout
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_timeout_ms(1.5)  # type: ignore

    def test_negative_timeout_raises(self):
        """
        GIVEN a negative timeout
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="≥"):
            validate_timeout_ms(-1)


class TestValidateFormat:
    """Tests for validate_format."""

    def test_auto_format_passes(self):
        """
        GIVEN 'auto' format
        WHEN validating
        THEN should not raise.
        """
        validate_format("auto")

    def test_tdfol_format_passes(self):
        """
        GIVEN 'tdfol' format
        WHEN validating
        THEN should not raise.
        """
        validate_format("tdfol")

    def test_dcec_format_passes(self):
        """
        GIVEN 'dcec' format
        WHEN validating
        THEN should not raise.
        """
        validate_format("dcec")

    def test_unsupported_format_raises(self):
        """
        GIVEN an unsupported format
        WHEN validating
        THEN should raise ValidationError.
        """
        with pytest.raises(ValidationError, match="Unsupported format"):
            validate_format("json_logic")

    def test_custom_supported_formats(self):
        """
        GIVEN a custom supported set
        WHEN validating with it
        THEN should use the custom set.
        """
        validate_format("myformat", supported={"myformat", "other"})

    def test_error_context_includes_supported_list(self):
        """
        GIVEN an unsupported format
        WHEN ValidationError is raised
        THEN error context should include supported formats.
        """
        with pytest.raises(ValidationError) as exc_info:
            validate_format("invalid_fmt")
        assert exc_info.value.context.get("supported") is not None
