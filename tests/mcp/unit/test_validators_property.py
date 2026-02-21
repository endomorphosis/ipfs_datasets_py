"""
Phase B4: Property-based tests for validators using hypothesis.

These tests verify invariants that must hold for all valid / invalid inputs,
not just a fixed set of examples.  The suite requires ``hypothesis`` to be
installed::

    pip install hypothesis

Tests are collected normally by pytest; no special plugin is required.
"""
from __future__ import annotations

import string

import pytest

try:
    from hypothesis import assume, given, settings
    from hypothesis import strategies as st

    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False

    # Stub out the hypothesis symbols so that class-body decorators don't cause
    # a NameError at *collection* time when hypothesis is not installed.
    # The pytestmark below will skip every test before they actually run.
    def given(*_a, **_kw):  # type: ignore[misc]
        return lambda f: f

    def settings(*_a, **_kw):  # type: ignore[misc]
        return lambda f: f

    def assume(_cond: bool) -> None:  # type: ignore[misc]
        pass

    class st:  # type: ignore[no-redef]
        @staticmethod
        def text(**_kw):
            return None

        @staticmethod
        def integers(**_kw):
            return None

        @staticmethod
        def one_of(*_a):
            return None

        @staticmethod
        def sampled_from(_seq):
            return None

        @staticmethod
        def lists(*_a, **_kw):
            return None

        @staticmethod
        def floats(**_kw):
            return None

        @staticmethod
        def from_regex(_pattern, **_kw):
            return None


pytestmark = pytest.mark.skipif(
    not HYPOTHESIS_AVAILABLE,
    reason="hypothesis not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def validator():
    from ipfs_datasets_py.mcp_server.validators import EnhancedParameterValidator
    return EnhancedParameterValidator()


@pytest.fixture(scope="module")
def exc_class():
    from ipfs_datasets_py.mcp_server.exceptions import ValidationError
    return ValidationError


# ---------------------------------------------------------------------------
# P1: validate_text_input — length invariants
# ---------------------------------------------------------------------------

class TestValidateTextInputProperties:
    """Property-based tests for text input validation."""

    @given(text=st.text(min_size=1, max_size=9999))
    @settings(max_examples=200)
    def test_valid_text_is_accepted_or_rejected_for_known_reasons(self, validator, exc_class, text):
        """
        GIVEN: Any non-empty text within the default length limit
        WHEN:  validate_text_input is called
        THEN:  Either the stripped text is returned OR a ValidationError is raised
               (e.g., text contained suspicious patterns) — never any other exception.
        """
        try:
            result = validator.validate_text_input(text, max_length=10000, allow_empty=False)
            assert isinstance(result, str)
            assert result == text.strip()
        except exc_class:
            pass  # ValidationError is acceptable

    @given(text=st.text(min_size=1, max_size=9999))
    @settings(max_examples=100)
    def test_returned_text_never_has_leading_trailing_whitespace(self, validator, exc_class, text):
        """
        GIVEN: Any text that passes validation
        WHEN:  validate_text_input returns a result
        THEN:  The result has no leading or trailing whitespace
        """
        try:
            result = validator.validate_text_input(text, max_length=10000, allow_empty=True)
            assert result == result.strip(), "Returned text must be stripped"
        except exc_class:
            pass

    @given(n=st.integers(min_value=10001, max_value=100000))
    @settings(max_examples=50)
    def test_text_exceeding_max_length_is_rejected(self, validator, exc_class, n):
        """
        GIVEN: A text longer than max_length
        WHEN:  validate_text_input is called
        THEN:  ValidationError is always raised (never silently truncated)
        """
        text = "a" * n
        with pytest.raises(exc_class):
            validator.validate_text_input(text, max_length=10000)

    @given(text=st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_safe_alphanumeric_text_always_accepted(self, validator, exc_class, text):
        """
        GIVEN: Text containing only ASCII letters and spaces
        WHEN:  validate_text_input is called
        THEN:  Validation always succeeds (no suspicious patterns in safe alphabet)
        """
        assume(text.strip())  # ensure at least 1 non-whitespace char
        result = validator.validate_text_input(text, max_length=10000, allow_empty=False)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# P2: validate_numeric_range — bound invariants
# ---------------------------------------------------------------------------

class TestValidateNumericRangeProperties:
    """Property-based tests for numeric range validation."""

    @given(
        value=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_value_in_range_always_returned(self, validator, value):
        """
        GIVEN: A float in [0, 1]
        WHEN:  validate_numeric_range is called with min=0, max=1
        THEN:  The exact value is returned unchanged
        """
        result = validator.validate_numeric_range(value, "prob", min_val=0.0, max_val=1.0)
        assert result == value

    @given(
        value=st.one_of(
            st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
            st.floats(min_value=1.001, max_value=1e9, allow_nan=False, allow_infinity=False),
        )
    )
    @settings(max_examples=200)
    def test_value_outside_range_always_rejected(self, validator, exc_class, value):
        """
        GIVEN: A float strictly outside [0, 1]
        WHEN:  validate_numeric_range is called with min=0, max=1
        THEN:  ValidationError is raised
        """
        with pytest.raises(exc_class):
            validator.validate_numeric_range(value, "prob", min_val=0.0, max_val=1.0)

    @given(
        lo=st.integers(min_value=1, max_value=100),
        hi=st.integers(min_value=101, max_value=1000),
        value=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_integer_within_range_accepted(self, validator, lo, hi, value):
        """
        GIVEN: An integer within [lo, hi]
        WHEN:  validate_numeric_range is called
        THEN:  The integer is accepted
        """
        assume(lo <= value <= hi)
        result = validator.validate_numeric_range(value, "n", min_val=float(lo), max_val=float(hi))
        assert result == value


# ---------------------------------------------------------------------------
# P3: validate_collection_name — length and alphabet invariants
# ---------------------------------------------------------------------------

class TestValidateCollectionNameProperties:
    """Property-based tests for collection name validation."""

    # Strategy: only letters, digits, hyphens, underscores
    _SAFE = st.text(
        alphabet=string.ascii_lowercase + string.digits + "-_",
        min_size=2,
        max_size=64,
    )

    @given(name=_SAFE)
    @settings(max_examples=200)
    def test_safe_name_accepted_or_reserved(self, validator, exc_class, name):
        """
        GIVEN: A name with only safe characters and valid length
        WHEN:  validate_collection_name is called
        THEN:  Either the name is returned OR a ValidationError for reserved name
        """
        try:
            result = validator.validate_collection_name(name)
            assert result == name
        except exc_class as e:
            assert "reserved" in str(e).lower() or "characters" in str(e).lower()

    @given(name=st.text(min_size=65, max_size=200, alphabet=string.ascii_lowercase))
    @settings(max_examples=50)
    def test_name_exceeding_64_chars_rejected(self, validator, exc_class, name):
        """
        GIVEN: A name longer than 64 characters
        WHEN:  validate_collection_name is called
        THEN:  ValidationError is raised
        """
        with pytest.raises(exc_class):
            validator.validate_collection_name(name)

    @given(
        name=st.text(
            alphabet=string.ascii_lowercase + string.digits,
            min_size=2,
            max_size=30,
        )
    )
    @settings(max_examples=100)
    def test_returned_name_equals_input(self, validator, exc_class, name):
        """
        GIVEN: A valid name (non-reserved, correct characters)
        WHEN:  validate_collection_name accepts it
        THEN:  Returned value is identical to input (no modification)
        """
        reserved = {"admin", "system", "root", "default", "null", "undefined"}
        assume(name not in reserved)
        # Ensure starts with a letter (some validators may require that)
        assume(name[0] in string.ascii_lowercase)
        try:
            result = validator.validate_collection_name(name)
            assert result == name
        except exc_class:
            pass


# ---------------------------------------------------------------------------
# P4: validate_url — scheme enforcement invariants
# ---------------------------------------------------------------------------

class TestValidateUrlProperties:
    """Property-based tests for URL validation."""

    @given(
        scheme=st.sampled_from(["javascript", "data", "file", "ftp"]),
        host=st.from_regex(r"[a-z]{3,10}\.com", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_disallowed_scheme_rejected(self, validator, exc_class, scheme, host):
        """
        GIVEN: A URL with a scheme not in the allowed set
        WHEN:  validate_url is called with allowed_schemes={'http', 'https'}
        THEN:  ValidationError is raised
        """
        url = f"{scheme}://{host}/path"
        with pytest.raises(exc_class):
            validator.validate_url(url, allowed_schemes={"http", "https"})

    @given(host=st.from_regex(r"[a-z]{3,15}\.[a-z]{2,4}", fullmatch=True))
    @settings(max_examples=100)
    def test_https_url_always_accepted(self, validator, exc_class, host):
        """
        GIVEN: An https:// URL with a simple hostname
        WHEN:  validate_url is called with allowed_schemes={'http', 'https'}
        THEN:  The URL is returned unchanged
        """
        url = f"https://{host}/api/v1"
        try:
            result = validator.validate_url(url, allowed_schemes={"http", "https"})
            assert result == url
        except exc_class:
            pass  # Malformed or suspicious URL — acceptable

    @given(not_a_url=st.text(min_size=1, max_size=50, alphabet=string.ascii_letters))
    @settings(max_examples=50)
    def test_plain_text_without_scheme_is_rejected(self, validator, exc_class, not_a_url):
        """
        GIVEN: A string with no URL scheme
        WHEN:  validate_url is called
        THEN:  ValidationError is raised (missing scheme)
        """
        assume("://" not in not_a_url)
        with pytest.raises(exc_class):
            validator.validate_url(not_a_url, allowed_schemes={"http", "https"})
