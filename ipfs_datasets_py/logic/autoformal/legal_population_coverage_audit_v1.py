"""Count separate authored populations without extrapolating throughput.

Inventory, eligible, attempted, missing, invalid, unsupported, and accepted
counts stay on separate counters. A compared row stays compared. Every
attempted row carries one review record. The small replay is not scaled to
a corpus rate. This module calls no decoder, scores no federal corpus, and
records an authored fixture only.
"""

from __future__ import annotations

SCHEMA = "legal-population-coverage-audit/v1"
COVERAGE_BOUNDARY = """Inventory, eligible, attempted, missing, invalid, unsupported and accepted counts stay separate.
Compared is not an accepted population.
Attempted rows include a review record.
No throughput extrapolation from the small replay or the row-only total.
"""

_TERMINAL = frozenset(
    {
        "missing",
        "invalid_typed_output",
        "unsupported",
        "compared",
        "abstained",
    }
)
_FIXTURE = (
    {"eligible": False, "attempted": False, "status": "ineligible", "review_records": 0},
    {"eligible": True, "attempted": False, "status": "missing", "review_records": 0},
    {"eligible": True, "attempted": False, "status": "missing", "review_records": 0},
    {"eligible": True, "attempted": False, "status": "missing", "review_records": 0},
    {"eligible": True, "attempted": True, "status": "invalid_typed_output", "review_records": 1},
    {"eligible": True, "attempted": True, "status": "unsupported", "review_records": 1},
    {"eligible": True, "attempted": True, "status": "unsupported", "review_records": 1},
    {"eligible": True, "attempted": True, "status": "compared", "review_records": 1},
    {"eligible": True, "attempted": True, "status": "abstained", "review_records": 1},
)


class PopulationCoverageAuditError(ValueError):
    """A population was collapsed, a review record was omitted, or a rate was scaled."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise PopulationCoverageAuditError(message)


def _rows(rows: object) -> tuple[dict[str, object], ...]:
    _need(type(rows) is tuple and len(rows) == 9, "authored population stays the recorded fixture")
    checked: list[dict[str, object]] = []
    for item in rows:
        _need(
            type(item) is dict
            and set(item) == {"eligible", "attempted", "status", "review_records"},
            "authored population stays the recorded fixture",
        )
        eligible = item["eligible"]
        attempted = item["attempted"]
        status = item["status"]
        reviews = item["review_records"]
        _need(type(eligible) is bool and type(attempted) is bool, "eligibility stays boolean")
        _need(type(status) is str and status in _TERMINAL or status == "ineligible", "status stays named")
        _need(type(reviews) is int and reviews in (0, 1), "review records stay one or none")
        _need(attempted is False or eligible is True, "an ineligible row was attempted")
        _need(status != "accepted", "accepted is not a population status")
        checked.append(
            {
                "eligible": eligible,
                "attempted": attempted,
                "status": status,
                "review_records": reviews,
            }
        )
    return tuple(checked)


def _counts(rows: tuple[dict[str, object], ...], *, count_compared_as_accepted: bool) -> dict[str, int]:
    inventory = len(rows)
    eligible = sum(row["eligible"] is True for row in rows)
    attempted = sum(row["attempted"] is True for row in rows)
    missing = sum(row["status"] == "missing" for row in rows)
    invalid = sum(row["status"] == "invalid_typed_output" for row in rows)
    unsupported = sum(row["status"] == "unsupported" for row in rows)
    compared = sum(row["status"] == "compared" for row in rows)
    accepted = compared if count_compared_as_accepted else 0
    review_records = sum(int(row["review_records"]) for row in rows)
    return {
        "inventory_count": inventory,
        "eligible_count": eligible,
        "attempted_count": attempted,
        "missing_count": missing,
        "invalid_count": invalid,
        "unsupported_count": unsupported,
        "accepted_count": accepted,
        "compared_count": compared,
        "review_cost_record_count": review_records,
    }


def audit_population_coverage(*, refusal: str = "") -> dict[str, object]:
    """Record separate fixture counts and refuse collapsed or scaled totals."""

    rows = _rows(_FIXTURE)
    if refusal == "accepted-relabel":
        relabeled = _counts(rows, count_compared_as_accepted=True)
        _need(relabeled["accepted_count"] == relabeled["compared_count"], "compared was not available to relabel")
        raise PopulationCoverageAuditError("compared was counted as accepted")
    if refusal == "extrapolation":
        counted = _counts(rows, count_compared_as_accepted=False)
        scaled = counted["attempted_count"] * 1000
        _need(scaled != counted["inventory_count"], "scaled replay collapsed into the fixture")
        raise PopulationCoverageAuditError("throughput was extrapolated")
    if refusal == "omitted-review":
        omitted = tuple(
            {**row, "review_records": 0} if row["status"] == "compared" else row for row in rows
        )
        for row in omitted:
            if row["attempted"] is True and row["review_records"] != 1:
                raise PopulationCoverageAuditError("attempted row omitted its review record")
        raise PopulationCoverageAuditError("attempted row omitted its review record")
    _need(refusal == "", "unknown coverage refusal")
    for row in rows:
        if row["attempted"] is True:
            _need(row["review_records"] == 1, "attempted row omitted its review record")
        else:
            _need(row["review_records"] == 0, "an unattempted row carried a review record")
    counted = _counts(rows, count_compared_as_accepted=False)
    distinct = {
        counted["inventory_count"],
        counted["eligible_count"],
        counted["attempted_count"],
        counted["missing_count"],
        counted["invalid_count"],
        counted["unsupported_count"],
        counted["accepted_count"],
    }
    _need(len(distinct) == 7, "population counts were not separate")
    _need(counted["accepted_count"] == 0, "accepted population was invented")
    _need(counted["compared_count"] == 1, "compared row was dropped")
    _need(counted["review_cost_record_count"] == counted["attempted_count"], "review cost was not included")
    _need(counted["inventory_count"] != counted["attempted_count"], "row-only total replaced the inventory")
    return {
        "schema": SCHEMA,
        "authored_fixture_only": True,
        "inventory_count": counted["inventory_count"],
        "eligible_count": counted["eligible_count"],
        "attempted_count": counted["attempted_count"],
        "missing_count": counted["missing_count"],
        "invalid_count": counted["invalid_count"],
        "unsupported_count": counted["unsupported_count"],
        "accepted_count": counted["accepted_count"],
        "compared_count": counted["compared_count"],
        "compared_counted_as_accepted": False,
        "counts_are_distinct": True,
        "review_cost_included": True,
        "review_cost_record_count": counted["review_cost_record_count"],
        "review_cost_kind": "authored-fixture-review-record",
        "pilot_review_cost_measured": False,
        "throughput_extrapolated": False,
        "row_only_total_used_as_throughput": False,
        "decoder_executed": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }
