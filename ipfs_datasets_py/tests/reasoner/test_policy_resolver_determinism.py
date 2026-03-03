"""Tests for deterministic policy resolver (WS12-02)."""
from __future__ import annotations

import pytest
from reasoner.policy_resolver import (
    RESOLVER_SCHEMA_VERSION,
    RESOLVER_ERROR_CODES,
    PolicyResolutionError,
    resolve_policy_pack,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _pack(jurisdiction: str, effective_date: str, pack_id: str = None) -> dict:
    p = {
        "jurisdiction": jurisdiction,
        "effective_date": effective_date,
        "priority_policy": {},
        "exception_policy": {},
        "temporal_policy": {},
    }
    if pack_id is not None:
        p["pack_id"] = pack_id
    return p


PACKS_BASIC = [
    _pack("US-CA", "2023-01-01", "pack-a"),
    _pack("US-CA", "2024-06-01", "pack-b"),
    _pack("US-NY", "2024-01-01", "pack-ny"),
]


# ---------------------------------------------------------------------------
# TestReplayStability
# ---------------------------------------------------------------------------

class TestReplayStability:
    def test_same_inputs_return_same_result(self):
        # GIVEN the same packs, jurisdiction, and date
        r1 = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        r2 = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        # THEN selected_pack_id is identical both times (replay stable)
        assert r1["selected_pack_id"] == r2["selected_pack_id"]
        assert r1["selected_pack_index"] == r2["selected_pack_index"]

    def test_same_inputs_multiple_calls_deterministic(self):
        # GIVEN same inputs called many times
        results = [
            resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
            for _ in range(5)
        ]
        ids = [r["selected_pack_id"] for r in results]
        assert len(set(ids)) == 1, "resolve_policy_pack is not deterministic"


# ---------------------------------------------------------------------------
# TestMostRecentEffectiveDateWins
# ---------------------------------------------------------------------------

class TestMostRecentEffectiveDateWins:
    def test_most_recent_effective_date_selected(self):
        # GIVEN two packs for same jurisdiction, different dates
        packs = [
            _pack("US-CA", "2022-01-01", "old"),
            _pack("US-CA", "2024-01-01", "new"),
        ]
        result = resolve_policy_pack(packs, "US-CA", "2024-12-31")
        # THEN the newer pack is selected
        assert result["selected_pack_id"] == "new"

    def test_older_pack_not_selected_when_newer_exists(self):
        # GIVEN packs in reverse order
        packs = [
            _pack("US-CA", "2024-06-01", "mid"),
            _pack("US-CA", "2020-01-01", "old"),
        ]
        result = resolve_policy_pack(packs, "US-CA", "2025-01-01")
        assert result["selected_pack_id"] == "mid"


# ---------------------------------------------------------------------------
# TestTieBreakByPackId
# ---------------------------------------------------------------------------

class TestTieBreakByPackId:
    def test_tie_break_by_pack_id_lexicographic(self):
        # GIVEN two packs with same effective_date and different pack_ids
        packs = [
            _pack("US-TX", "2024-01-01", "pack-b"),
            _pack("US-TX", "2024-01-01", "pack-a"),
        ]
        result = resolve_policy_pack(packs, "US-TX", "2024-06-01")
        # THEN pack-a is selected (lexicographically first)
        assert result["selected_pack_id"] == "pack-a"
        assert result["tie_break_applied"] is True

    def test_tie_break_is_deterministic_regardless_of_input_order(self):
        # GIVEN same packs in different orders
        packs_order1 = [
            _pack("US-TX", "2024-01-01", "pack-z"),
            _pack("US-TX", "2024-01-01", "pack-a"),
        ]
        packs_order2 = [
            _pack("US-TX", "2024-01-01", "pack-a"),
            _pack("US-TX", "2024-01-01", "pack-z"),
        ]
        r1 = resolve_policy_pack(packs_order1, "US-TX", "2024-06-01")
        r2 = resolve_policy_pack(packs_order2, "US-TX", "2024-06-01")
        # THEN same pack_id is selected in both cases
        assert r1["selected_pack_id"] == r2["selected_pack_id"] == "pack-a"

    def test_no_tie_break_when_single_candidate(self):
        # GIVEN only one matching pack
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        assert result["tie_break_applied"] is False


# ---------------------------------------------------------------------------
# TestJurisdictionFiltering
# ---------------------------------------------------------------------------

class TestJurisdictionFiltering:
    def test_only_matching_jurisdiction_selected(self):
        # GIVEN packs from multiple jurisdictions
        result = resolve_policy_pack(PACKS_BASIC, "US-NY", "2024-12-01")
        assert result["selected_pack_id"] == "pack-ny"
        assert result["jurisdiction"] == "US-NY"

    def test_wrong_jurisdiction_raises_no_match(self):
        # GIVEN querying an unregistered jurisdiction
        with pytest.raises(PolicyResolutionError) as exc_info:
            resolve_policy_pack(PACKS_BASIC, "EU-DE", "2024-01-01")
        assert exc_info.value.error_code == RESOLVER_ERROR_CODES["no_matching_packs"]

    def test_jurisdiction_exact_match_required(self):
        # GIVEN "US" does not match "US-CA"
        with pytest.raises(PolicyResolutionError):
            resolve_policy_pack(PACKS_BASIC, "US", "2024-01-01")


# ---------------------------------------------------------------------------
# TestDateFiltering
# ---------------------------------------------------------------------------

class TestDateFiltering:
    def test_future_effective_date_not_selected(self):
        # GIVEN a pack with effective_date after query date
        packs = [
            _pack("US-CA", "2024-06-01", "future"),
            _pack("US-CA", "2023-01-01", "past"),
        ]
        result = resolve_policy_pack(packs, "US-CA", "2024-01-01")
        # THEN the past pack is selected (future not yet effective)
        assert result["selected_pack_id"] == "past"

    def test_effective_date_equal_to_query_date_is_included(self):
        # GIVEN effective_date == query date
        packs = [_pack("US-CA", "2024-06-01", "exact")]
        result = resolve_policy_pack(packs, "US-CA", "2024-06-01")
        assert result["selected_pack_id"] == "exact"

    def test_all_packs_future_raises_no_match(self):
        # GIVEN all packs have future effective dates
        packs = [_pack("US-CA", "2030-01-01", "future")]
        with pytest.raises(PolicyResolutionError) as exc_info:
            resolve_policy_pack(packs, "US-CA", "2024-01-01")
        assert exc_info.value.error_code == RESOLVER_ERROR_CODES["no_matching_packs"]


# ---------------------------------------------------------------------------
# TestNoMatchingPacks
# ---------------------------------------------------------------------------

class TestNoMatchingPacks:
    def test_empty_packs_list_raises(self):
        # GIVEN an empty packs list
        with pytest.raises(PolicyResolutionError) as exc_info:
            resolve_policy_pack([], "US-CA", "2024-01-01")
        assert exc_info.value.error_code == RESOLVER_ERROR_CODES["no_matching_packs"]

    def test_error_has_correct_code(self):
        # GIVEN no matching packs
        with pytest.raises(PolicyResolutionError) as exc_info:
            resolve_policy_pack([], "US-CA", "2024-01-01")
        err = exc_info.value
        assert err.error_code == "PR_ERR_NO_MATCHING_PACKS"
        assert isinstance(err.error_code, str)


# ---------------------------------------------------------------------------
# TestDecisionEnvelope
# ---------------------------------------------------------------------------

class TestDecisionEnvelope:
    def test_envelope_has_required_fields(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        # THEN all required fields are present
        for key in (
            "schema_version", "selected_pack_id", "selected_pack_index",
            "jurisdiction", "date", "tie_break_applied", "trace",
        ):
            assert key in result, f"Missing envelope field: {key}"

    def test_schema_version_in_envelope(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        # THEN schema_version matches constant
        assert result["schema_version"] == RESOLVER_SCHEMA_VERSION
        assert result["schema_version"] == "1.0"

    def test_jurisdiction_and_date_echoed_in_envelope(self):
        # GIVEN a specific jurisdiction and date
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-07-04")
        assert result["jurisdiction"] == "US-CA"
        assert result["date"] == "2024-07-04"

    def test_envelope_selected_pack_index_is_valid(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        idx = result["selected_pack_index"]
        assert isinstance(idx, int)
        assert 0 <= idx < len(PACKS_BASIC)


# ---------------------------------------------------------------------------
# TestTraceFields
# ---------------------------------------------------------------------------

class TestTraceFields:
    def test_trace_is_list(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        assert isinstance(result["trace"], list)
        assert len(result["trace"]) > 0

    def test_trace_contains_jurisdiction_filter_step(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        steps = [t["step"] for t in result["trace"]]
        assert "jurisdiction_filter" in steps

    def test_trace_contains_date_filter_step(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        steps = [t["step"] for t in result["trace"]]
        assert "date_filter" in steps

    def test_trace_contains_selected_step(self):
        # GIVEN a valid resolution
        result = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        steps = [t["step"] for t in result["trace"]]
        assert "selected" in steps

    def test_trace_deterministic_across_calls(self):
        # GIVEN the same inputs called twice
        r1 = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        r2 = resolve_policy_pack(PACKS_BASIC, "US-CA", "2024-12-01")
        # THEN traces have same steps in same order
        steps1 = [t["step"] for t in r1["trace"]]
        steps2 = [t["step"] for t in r2["trace"]]
        assert steps1 == steps2
