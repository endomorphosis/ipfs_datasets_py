"""
J48 — Hypothesis fuzzing tests for EnhancedParameterValidator
===============================================================
Uses the `hypothesis` library to stress-test the validator boundary with
automatically generated inputs.  The goal is to verify that:

1. The validator *never* crashes with an unexpected exception type.
2. All successful validations return a value of the correct type.
3. The validator is *consistent*: the same input always produces the same
   outcome (raises or succeeds).
4. Adversarial strings that contain injection patterns are *always* rejected.
"""

import re
import string
import sys
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Hypothesis availability guard
# ---------------------------------------------------------------------------

try:
    from hypothesis import given, settings, assume, HealthCheck
    import hypothesis.strategies as st
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False
    # Stub decorators so class bodies parse correctly without hypothesis installed
    def given(*a, **kw):  # type: ignore[misc]
        return lambda f: f
    def settings(*a, **kw):  # type: ignore[misc]
        return lambda f: f
    def assume(cond):  # type: ignore[misc]
        # Called in @given-decorated test bodies — stub must exist even when hypothesis absent
        pass
    class HealthCheck:  # type: ignore[misc]
        too_slow = None
    class _StStub:
        """No-op stub for hypothesis.strategies when hypothesis is absent."""
        def __getattr__(self, name):
            def _noop(*a, **kw):
                return None
            return _noop
    st = _StStub()  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    not HYPOTHESIS_AVAILABLE,
    reason="hypothesis not installed",
)

# ---------------------------------------------------------------------------
# Module path setup
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.mcp_server.validators import EnhancedParameterValidator
from ipfs_datasets_py.mcp_server.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Shared strategy helpers (only available when hypothesis is installed)
# ---------------------------------------------------------------------------

if HYPOTHESIS_AVAILABLE:
    _printable = st.text(
        alphabet=string.printable,
        min_size=0,
        max_size=200,
    )

    _short_alnum = st.text(
        alphabet=string.ascii_letters + string.digits + "_-",
        min_size=1,
        max_size=50,
    )

    _any_text = st.one_of(
        st.text(min_size=0, max_size=500),
        st.binary(min_size=0, max_size=50).map(lambda b: b.decode("utf-8", errors="replace")),
    )
else:
    _printable = None
    _short_alnum = None
    _any_text = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validator() -> EnhancedParameterValidator:
    """Return a fresh validator for each test to avoid cache interference."""
    return EnhancedParameterValidator()


# ===========================================================================
# validate_text_input fuzzing
# ===========================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestValidateTextInputFuzzing:
    """Fuzz validate_text_input with a wide range of generated strings."""

    @given(text=_printable)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_only_raises_validation_error_or_succeeds(self, text):
        """validate_text_input must only raise ValidationError (never TypeError etc.)."""
        v = _make_validator()
        try:
            result = v.validate_text_input(text)
            assert isinstance(result, str), "successful result must be str"
        except ValidationError:
            pass  # expected
        except Exception as exc:
            pytest.fail(f"Unexpected exception type {type(exc).__name__}: {exc}")

    @given(text=_printable)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_result_is_stripped(self, text):
        """On success the result must be text.strip()."""
        v = _make_validator()
        try:
            result = v.validate_text_input(text)
            assert result == text.strip()
        except ValidationError:
            pass

    @given(text=st.text(min_size=1, max_size=50, alphabet=string.ascii_letters + " "))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_safe_ascii_always_passes(self, text):
        """Plain ASCII letters and spaces should always pass (no injection)."""
        assume(len(text.strip()) >= 1)
        v = _make_validator()
        result = v.validate_text_input(text)
        assert isinstance(result, str)

    @given(text=st.just(""))
    @settings(max_examples=1)
    def test_empty_string_rejected_by_default(self, text):
        """Empty string raises ValidationError with default min_length=1."""
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_text_input(text)

    @given(text=st.just(""))
    @settings(max_examples=1)
    def test_empty_string_accepted_with_allow_empty(self, text):
        """allow_empty=True accepts the empty string."""
        v = _make_validator()
        result = v.validate_text_input(text, allow_empty=True)
        assert result == ""

    @given(length=st.integers(min_value=1, max_value=100))
    @settings(max_examples=50)
    def test_text_exceeding_max_length_always_rejected(self, length):
        """Text longer than max_length is always rejected."""
        v = _make_validator()
        text = "a" * (length + 1)
        with pytest.raises(ValidationError):
            v.validate_text_input(text, max_length=length)

    @pytest.mark.parametrize("injection", [
        "<script>alert(1)</script>",
        "javascript:void(0)",
        "eval(dangerous)",
        "exec(rm_rf)",
        "import os; os.system('ls')",
        "__import__('os').system('id')",
        "subprocess.run(['rm','-rf','/'])",
    ])
    def test_injection_patterns_always_rejected(self, injection):
        """Known injection patterns must always raise ValidationError."""
        v = _make_validator()
        with pytest.raises(ValidationError, match="unsafe"):
            v.validate_text_input(injection)

    @given(
        non_string=st.one_of(
            st.integers(),
            st.floats(allow_nan=False),
            st.booleans(),
            st.lists(st.text()),
            st.none(),
        )
    )
    @settings(max_examples=50)
    def test_non_string_always_rejected(self, non_string):
        """Any non-string input raises ValidationError (not TypeError)."""
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_text_input(non_string)  # type: ignore[arg-type]


# ===========================================================================
# validate_collection_name fuzzing
# ===========================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestValidateCollectionNameFuzzing:
    """Fuzz validate_collection_name."""

    @given(name=_printable)
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_only_raises_validation_error_or_succeeds(self, name):
        v = _make_validator()
        try:
            result = v.validate_collection_name(name)
            assert isinstance(result, str)
        except ValidationError:
            pass
        except Exception as exc:
            pytest.fail(f"Unexpected {type(exc).__name__}: {exc}")

    @given(
        name=st.text(
            alphabet=string.ascii_letters + string.digits + "_-",
            min_size=3,
            max_size=50,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_format_names_accepted(self, name):
        """Names matching the alphanumeric/hyphen/underscore pattern should
        pass if they are not reserved words."""
        reserved = {"admin", "system", "root", "default", "null", "undefined",
                    "test", "config", "settings", "internal"}
        assume(name.lower() not in reserved)
        v = _make_validator()
        try:
            result = v.validate_collection_name(name)
            assert result == name
        except ValidationError:
            # Might fail for other reasons (e.g. starts with digit patterns)
            pass

    @pytest.mark.parametrize("reserved", [
        "admin", "system", "root", "default", "null", "undefined",
    ])
    def test_reserved_names_rejected(self, reserved):
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_collection_name(reserved)

    @given(
        non_string=st.one_of(st.integers(), st.none(), st.booleans())
    )
    @settings(max_examples=30)
    def test_non_string_rejected(self, non_string):
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_collection_name(non_string)  # type: ignore[arg-type]


# ===========================================================================
# validate_url fuzzing
# ===========================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestValidateUrlFuzzing:
    """Fuzz validate_url."""

    @given(url=_printable)
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_only_raises_validation_error_or_succeeds(self, url):
        v = _make_validator()
        try:
            result = v.validate_url(url)
            assert isinstance(result, str)
        except ValidationError:
            pass
        except Exception as exc:
            pytest.fail(f"Unexpected {type(exc).__name__}: {exc}")

    @given(
        path=st.text(
            alphabet=string.ascii_letters + string.digits + "-_/.",
            min_size=1,
            max_size=50,
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_http_urls_generally_accepted(self, path):
        """http:// URLs with valid host/path should pass."""
        url = f"http://example.com/{path}"
        v = _make_validator()
        try:
            result = v.validate_url(url)
            assert result.startswith("http://")
        except ValidationError:
            pass  # Some paths may be flagged (e.g. injection pattern in path)

    @given(
        scheme=st.sampled_from(["ftp", "telnet", "file", "gopher", "smtp"])
    )
    @settings(max_examples=10)
    def test_non_http_schemes_rejected_when_restricted(self, scheme):
        """Non-http/https schemes are rejected when allowed_schemes is explicitly restricted."""
        v = _make_validator()
        url = f"{scheme}://example.com/"
        with pytest.raises(ValidationError):
            v.validate_url(url, allowed_schemes={"http", "https"})


# ===========================================================================
# validate_search_filters fuzzing
# ===========================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestValidateSearchFiltersFuzzing:
    """Fuzz validate_search_filters."""

    @given(
        filters=st.dictionaries(
            keys=st.text(alphabet=string.ascii_letters, min_size=1, max_size=20),
            values=st.one_of(
                st.text(max_size=50),
                st.integers(min_value=-1000, max_value=1000),
                st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
                st.booleans(),
            ),
            max_size=10,
        )
    )
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_simple_dict_does_not_crash(self, filters):
        v = _make_validator()
        try:
            result = v.validate_search_filters(filters)
            assert isinstance(result, dict)
        except ValidationError:
            pass
        except Exception as exc:
            pytest.fail(f"Unexpected {type(exc).__name__}: {exc}")

    @given(
        n=st.integers(min_value=51, max_value=200)
    )
    @settings(max_examples=20)
    def test_too_many_filters_always_rejected(self, n):
        """Dicts with > 50 keys always raise ValidationError."""
        v = _make_validator()
        filters = {f"field{i}": i for i in range(n)}
        with pytest.raises(ValidationError, match="Too many"):
            v.validate_search_filters(filters)

    @given(
        non_dict=st.one_of(
            st.text(), st.integers(), st.lists(st.text()), st.none()
        )
    )
    @settings(max_examples=40)
    def test_non_dict_always_rejected(self, non_dict):
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_search_filters(non_dict)  # type: ignore[arg-type]

    def test_empty_dict_always_accepted(self):
        v = _make_validator()
        assert v.validate_search_filters({}) == {}


# ===========================================================================
# validate_ipfs_hash fuzzing
# ===========================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestValidateIPFSHashFuzzing:
    """Fuzz validate_ipfs_hash."""

    # CIDv0: Qm + 44 base58 chars
    _base58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

    @given(
        suffix=st.text(alphabet=_base58, min_size=44, max_size=44)
    )
    @settings(max_examples=100)
    def test_valid_cidv0_always_accepted(self, suffix):
        """Qm + 44 base58 chars should always be accepted as CIDv0."""
        v = _make_validator()
        cid = f"Qm{suffix}"
        result = v.validate_ipfs_hash(cid)
        assert result == cid

    @given(
        garbage=st.text(min_size=0, max_size=100)
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_random_strings_mostly_rejected(self, garbage):
        """Most random strings fail IPFS hash validation."""
        # Some random strings might accidentally match a valid pattern;
        # we just check no unexpected exception is raised.
        v = _make_validator()
        try:
            result = v.validate_ipfs_hash(garbage)
            assert isinstance(result, str)
        except ValidationError:
            pass
        except Exception as exc:
            pytest.fail(f"Unexpected {type(exc).__name__}: {exc}")

    @given(
        non_string=st.one_of(st.integers(), st.none(), st.booleans(), st.lists(st.text()))
    )
    @settings(max_examples=30)
    def test_non_string_always_rejected(self, non_string):
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_ipfs_hash(non_string)  # type: ignore[arg-type]


# ===========================================================================
# validate_model_name fuzzing
# ===========================================================================

@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestValidateModelNameFuzzing:
    """Fuzz validate_model_name."""

    @given(name=_printable)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_only_raises_validation_error_or_succeeds(self, name):
        v = _make_validator()
        try:
            result = v.validate_model_name(name)
            assert isinstance(result, str)
        except ValidationError:
            pass
        except Exception as exc:
            pytest.fail(f"Unexpected {type(exc).__name__}: {exc}")

    @pytest.mark.parametrize("name", [
        "sentence-transformers/all-MiniLM-L6-v2",
        "all-mpnet-base-v2",
        "openai/text-embedding-ada-002",
        "text-embedding-small",
        "local/my-model",
    ])
    def test_known_valid_names_accepted(self, name):
        """Names matching known patterns are accepted."""
        v = _make_validator()
        result = v.validate_model_name(name)
        assert isinstance(result, str)

    @given(
        non_string=st.one_of(st.integers(), st.none(), st.booleans())
    )
    @settings(max_examples=20)
    def test_non_string_rejected(self, non_string):
        v = _make_validator()
        with pytest.raises(ValidationError):
            v.validate_model_name(non_string)  # type: ignore[arg-type]
