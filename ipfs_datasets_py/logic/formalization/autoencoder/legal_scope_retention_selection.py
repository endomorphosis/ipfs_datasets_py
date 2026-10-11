"""Pure measured-case selection with aggregate and paired retention floors.

Cases are scorer observations joined to the declared selection references only.
Their hashes authenticate recorded source identity, not inference execution or
legal meaning. The actual measured cold step-zero candidate remains a fallback;
selection says nothing about a later final or exposed retention panel.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

CONFIG_SCHEMA = "legal-scope-retention-selection-config/v1"
PANEL_SCHEMA = "legal-scope-retention-selection-panel/v1"
DECISION_SCHEMA = "legal-scope-retention-selection-decision/v1"
SOURCE_PROFILE = "fresh-support-retention-20261011/v1"
ALLOWED_COMPLETED_UPDATES = (0, 120, 240)
MAX_CASES = 8192
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,191}\Z")
_CASE_FIELDS = frozenset(("id", "source_group", "source_sha256", "supported",
                          "emitted", "whole_exact", "learned_refusal"))
_COUNTERS = (
    "case_count", "source_parent_groups", "positive_count", "negative_count",
    "positive_exact_count", "positive_emitted_proposal_count",
    "positive_learned_refusal_count", "positive_structural_block_count",
    "negative_emitted_proposal_count", "negative_learned_refusal_count",
    "negative_incidental_block_count",
)
_SET_COUNTS = {
    "positive_ids": "positive_count",
    "negative_ids": "negative_count",
    "positive_exact_ids": "positive_exact_count",
    "positive_emitted_proposal_ids": "positive_emitted_proposal_count",
    "positive_learned_refusal_ids": "positive_learned_refusal_count",
    "positive_structural_block_ids": "positive_structural_block_count",
    "negative_emitted_proposal_ids": "negative_emitted_proposal_count",
    "negative_learned_refusal_ids": "negative_learned_refusal_count",
    "negative_incidental_block_ids": "negative_incidental_block_count",
}
_SUMMARY_FIELDS = frozenset((*_COUNTERS, *_SET_COUNTS, "source_groups"))


class RetentionSelectionError(ValueError):
    """Measured cases, identities, counters or checkpoint ordering disagree."""


def _require(condition, message):
    if not condition:
        raise RetentionSelectionError(message)


def _integer(value, message, *, minimum=0, maximum=MAX_CASES):
    _require(type(value) is int and minimum <= value <= maximum, message)


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Pin one paired source profile and its complete measured denominator."""

    source_profile: str = SOURCE_PROFILE
    positive_count: int = 64
    negative_count: int = 64
    source_parent_groups: int = 64

    def __post_init__(self):
        _require(self.source_profile == SOURCE_PROFILE
                 and type(self.source_profile) is str, "declared source profile required")
        for name in ("positive_count", "negative_count", "source_parent_groups"):
            _integer(getattr(self, name), "positive integer profile denominator required",
                     minimum=1, maximum=MAX_CASES // 2)
        _require(self.positive_count == self.negative_count == self.source_parent_groups,
                 "profile requires one positive and one paired negative per source group")

    def to_dict(self):
        self.__post_init__()
        return {"schema": CONFIG_SCHEMA, **asdict(self)}

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == {"schema", *cls.__dataclass_fields__}
                 and value["schema"] == CONFIG_SCHEMA, "closed selection config required")
        return cls(**{key: value[key] for key in cls.__dataclass_fields__})


def _config(config):
    _require(type(config) is SelectionConfig, "typed selection config required")
    config.__post_init__()
    return config


def _cases(cases, config):
    _config(config)
    _require(type(cases) is list and len(cases) == config.positive_count + config.negative_count,
             "complete profile case denominator required")
    identities, hashes, groups, rows = set(), set(), {}, []
    for row in cases:
        _require(type(row) is dict and set(row) == _CASE_FIELDS, "closed measured case required")
        source_hash = row["source_sha256"]
        _require(type(source_hash) is str and _HASH.fullmatch(source_hash) is not None,
                 "exact source SHA256 required")
        identity = row["id"]
        _require(type(identity) is str and identity == "source:" + source_hash,
                 "source ID must bind exact source SHA256")
        _require(identity not in identities and source_hash not in hashes,
                 "unique source IDs and source hashes required")
        group = row["source_group"]
        _require(type(group) is str and _IDENTIFIER.fullmatch(group) is not None,
                 "bounded source group identity required")
        for field in ("supported", "emitted", "whole_exact", "learned_refusal"):
            _require(type(row[field]) is bool, "ordinary boolean case observations required")
        _require(not (row["emitted"] and row["learned_refusal"]),
                 "emission and learned refusal must be disjoint")
        _require(not row["whole_exact"] or (row["supported"] and row["emitted"]),
                 "whole exactness requires an emitted positive case")
        identities.add(identity)
        hashes.add(source_hash)
        groups.setdefault(group, {"positive_ids": [], "negative_ids": []})[
            "positive_ids" if row["supported"] else "negative_ids"].append(identity)
        rows.append(dict(row))
    _require(len(groups) == config.source_parent_groups,
             "complete source group denominator required")
    _require(all(len(value["positive_ids"]) == len(value["negative_ids"]) == 1
                 for value in groups.values()),
             "each source group requires exactly one positive and its paired negative")
    return sorted(rows, key=lambda row: row["id"]), {
        key: groups[key] for key in sorted(groups)
    }


def summarize_cases(cases, config=SelectionConfig()):
    """Derive every selection counter and ID set from complete unique cases."""
    rows, groups = _cases(cases, config)
    result = {key: [] for key in _SET_COUNTS}
    for row in rows:
        prefix = "positive" if row["supported"] else "negative"
        result[prefix + "_ids"].append(row["id"])
        if row["emitted"]:
            result[prefix + "_emitted_proposal_ids"].append(row["id"])
        elif row["learned_refusal"]:
            result[prefix + "_learned_refusal_ids"].append(row["id"])
        else:
            block = "structural" if row["supported"] else "incidental"
            result[prefix + "_" + block + "_block_ids"].append(row["id"])
        if row["whole_exact"]:
            result["positive_exact_ids"].append(row["id"])
    result.update({counter: len(result[field]) for field, counter in _SET_COUNTS.items()})
    result.update(case_count=len(rows), source_parent_groups=len(groups), source_groups=groups)
    return result


def make_panel(cases, config=SelectionConfig()):
    """Create a detached closed panel; no model, source parser or final labels."""
    rows, _ = _cases(cases, config)
    return {"schema": PANEL_SCHEMA, "source_profile": config.source_profile,
            "cases": rows, "summary": summarize_cases(rows, config)}


def validate_panel(panel, config=SelectionConfig()):
    """Recompute sets, group memberships and counts before accepting a panel."""
    _config(config)
    _require(type(panel) is dict and set(panel) == {"schema", "source_profile", "cases", "summary"}
             and panel["schema"] == PANEL_SCHEMA
             and panel["source_profile"] == config.source_profile, "closed measured panel required")
    summary = panel["summary"]
    _require(type(summary) is dict and set(summary) == _SUMMARY_FIELDS,
             "closed complete selection summary required")
    for field in _COUNTERS:
        _integer(summary[field], "nonnegative ordinary integer selection counters required")
    for field, counter in _SET_COUNTS.items():
        values = summary[field]
        _require(type(values) is list and all(type(value) is str for value in values)
                 and len(values) == len(set(values)) and values == sorted(values)
                 and len(values) == summary[counter], "selection count/ID-set drift")
    _require(type(summary["source_groups"]) is dict, "source group membership ledger required")
    expected = make_panel(panel["cases"], config)
    _require(summary == expected["summary"], "measured cases, source groups and summary differ")
    return expected


def _paired(panel, baseline, config):
    current, before = validate_panel(panel, config), validate_panel(baseline, config)
    identity = lambda row: (row["id"], row["source_sha256"], row["source_group"], row["supported"])
    _require([identity(row) for row in current["cases"]] == [identity(row) for row in before["cases"]],
             "candidate and baseline source membership/group contracts differ")
    _require(before["summary"]["positive_exact_count"] > 0
             and before["summary"]["positive_emitted_proposal_count"] > 0,
             "nonzero baseline positive whole exactness and emission required before fitting")
    return current["summary"], before["summary"]


def retention_report(panel, baseline, config=SelectionConfig()):
    """Report every floor and exact paired change; aggregate swaps cannot pass."""
    current, before = _paired(panel, baseline, config)
    changes = {}
    for label, field in (("whole", "positive_exact_ids"),
                         ("positive_emission", "positive_emitted_proposal_ids"),
                         ("negative_emission", "negative_emitted_proposal_ids")):
        old, new = set(before[field]), set(current[field])
        for suffix, ids in (("retained", old & new), ("lost", old - new), ("gained", new - old)):
            changes[label + "_" + suffix] = sorted(ids)
    floors = {
        "positive_whole_count_retained": current["positive_exact_count"] >= before["positive_exact_count"],
        "positive_emission_count_retained": current["positive_emitted_proposal_count"] >= before["positive_emitted_proposal_count"],
        "positive_learned_refusal_count_not_increased": current["positive_learned_refusal_count"] <= before["positive_learned_refusal_count"],
        "negative_emission_count_not_increased": current["negative_emitted_proposal_count"] <= before["negative_emitted_proposal_count"],
        "baseline_exact_positive_ids_retained": not changes["whole_lost"],
        "baseline_emitted_positive_ids_retained": not changes["positive_emission_lost"],
        "no_new_negative_emission_ids": not changes["negative_emission_gained"],
    }
    allowed = all(floors.values())
    return {"eligible": allowed, "floors": floors,
            "failures": [key for key, passed in floors.items() if not passed],
            "paired_case_ids": changes, "paired_counts": {key: len(value) for key, value in changes.items()},
            "has_selection_gain": allowed and bool(changes["negative_emission_lost"] or changes["whole_gained"])}


def eligible(panel, baseline, config=SelectionConfig()):
    return retention_report(panel, baseline, config)["eligible"]


def _steps(steps):
    _require(type(steps) is int and steps in ALLOWED_COMPLETED_UPDATES,
             "actual completed updates must be 0, 120 or 240")


def rank(panel, steps, config=SelectionConfig()):
    """Rank measured rows only after a caller applies eligibility floors."""
    _steps(steps)
    summary = validate_panel(panel, config)["summary"]
    return (-summary["negative_emitted_proposal_count"], summary["positive_exact_count"],
            summary["negative_learned_refusal_count"], -steps)


def select(candidates, baseline, config=SelectionConfig()):
    """Return the original chosen candidate and a detached scoped decision.

    Increasing partial schedules are allowed, beginning with the measured cold
    zero. Only completed checkpoints at the three predeclared steps can enter.
    A fitted choice gains only by removing a baseline negative emission or
    gaining whole exactness; an eligible tie is not declared an improvement.
    """
    baseline = validate_panel(baseline, config)
    _require(type(candidates) is list and 1 <= len(candidates) <= len(ALLOWED_COMPLETED_UPDATES),
             "measured cold step-zero fallback must be first")
    previous, reports, allowed = -1, [], []
    for row in candidates:
        _require(type(row) is dict and set(row) == {"completed_updates", "panel", "checkpoint_sha256"},
                 "closed measured candidate required")
        step = row["completed_updates"]
        _steps(step)
        _require(step > previous, "candidate actual updates must be distinct and increasing")
        previous = step
        checkpoint = row["checkpoint_sha256"]
        _require(type(checkpoint) is str and _HASH.fullmatch(checkpoint) is not None,
                 "exact measured checkpoint SHA256 required")
        panel = validate_panel(row["panel"], config)
        if len(reports) == 0:
            _require(step == 0 and panel == baseline,
                     "actual measured cold step-zero panel must equal baseline")
        report = retention_report(panel, baseline, config)
        report.update(completed_updates=step, checkpoint_sha256=checkpoint,
                      fitted_selection_gain=step > 0 and report["has_selection_gain"])
        reports.append(report)
        if report["eligible"]:
            allowed.append(row)
    chosen = max(allowed, key=lambda row: rank(row["panel"], row["completed_updates"], config))
    selected = next(item for item in reports if item["completed_updates"] == chosen["completed_updates"])
    decision = {"schema": DECISION_SCHEMA, "config": config.to_dict(),
                "selected_completed_updates": chosen["completed_updates"],
                "selected_checkpoint_sha256": chosen["checkpoint_sha256"],
                "selected_fitted_gain": selected["fitted_selection_gain"],
                "candidates": reports, "final_retention_guaranteed": False,
                "source_semantics_verified": False, "proof_authority": False,
                "training_admission": False}
    return chosen, decision
