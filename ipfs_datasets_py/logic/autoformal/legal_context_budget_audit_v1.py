"""Audit one declared decoder budget without executing a decoder.

Context, no-context, shuffled, unrelated-context, and retrieval-only
controls share one decoder id and one source budget. Definition pin keys
stay separate from context pin keys. A cross-split context allowance is
not granted. This module calls no decoder, scores no federal corpus, and
records an authored fixture only.
"""

from __future__ import annotations

SCHEMA = "legal-context-budget-audit/v1"
DECODER_ID = "declared-relational-decoder"
SOURCE_BUDGET = "authored-source-budget"
CONTROL_NAMES = (
    "context",
    "no-context",
    "shuffled",
    "unrelated-context",
    "retrieval-only",
)
CONTEXT_BUDGET_BOUNDARY = """Context, no-context, shuffled, unrelated-context and retrieval-only controls share one decoder and one source budget.
Definition dependencies stay separate from context pins.
Cross-split context allowance is not granted.
No decoder was executed.
"""


class ContextBudgetAuditError(ValueError):
    """A control budget differed, a decoder ran, or a context pin was granted."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ContextBudgetAuditError(message)


def _pin_keys(value: object) -> tuple[str, ...]:
    _need(
        type(value) in (tuple, list) and len(value) > 0,
        "definition and context pins stay explicit",
    )
    keys: list[str] = []
    for item in value:
        _need(type(item) is str and bool(item), "definition and context pins stay explicit")
        keys.append(item)
    _need(len(set(keys)) == len(keys), "definition and context pins stay explicit")
    return tuple(keys)


def audit_context_budget(
    definition_pin_keys: tuple[str, ...] | list[str],
    context_pin_keys: tuple[str, ...] | list[str],
    controls: tuple[object, ...] | list[object],
    *,
    decoder_executed: bool = False,
    cross_split_context_allowance_count: int = 0,
    cross_split_context_allowance_granted: bool = False,
) -> dict[str, object]:
    """Record separated pins and one shared unexecuted budget.

    The allowance count must be the empty overlap. A granted allowance, a
    positive count, a second decoder, a second budget, or a decoder call
    is refused.
    """

    definition_keys = _pin_keys(definition_pin_keys)
    context_keys = _pin_keys(context_pin_keys)
    _need(
        set(definition_keys).isdisjoint(context_keys),
        "definition pins overlap context pins",
    )
    _need(
        type(controls) in (tuple, list) and len(controls) == len(CONTROL_NAMES),
        "controls are not explicit",
    )
    names: list[str] = []
    for row in controls:
        _need(
            type(row) is dict
            and set(row) == {"name", "decoder_id", "source_budget"},
            "controls are not explicit",
        )
        name = row["name"]
        decoder_id = row["decoder_id"]
        source_budget = row["source_budget"]
        _need(type(name) is str and type(decoder_id) is str and type(source_budget) is str,
              "controls are not explicit")
        _need(decoder_id == DECODER_ID, "controls do not share one decoder")
        _need(source_budget == SOURCE_BUDGET, "controls do not share one source budget")
        names.append(name)
    _need(tuple(names) == CONTROL_NAMES, "controls are not explicit")
    _need(decoder_executed is False, "decoder stays unexecuted")
    _need(
        cross_split_context_allowance_granted is False
        and type(cross_split_context_allowance_count) is int
        and cross_split_context_allowance_count == 0,
        "cross-split context allowance is not granted",
    )
    return {
        "schema": SCHEMA,
        "authored_fixture_only": True,
        "definition_pin_keys": list(definition_keys),
        "context_pin_keys": list(context_keys),
        "definition_pins_separate_from_context_pins": True,
        "control_names": list(CONTROL_NAMES),
        "decoder_id": DECODER_ID,
        "source_budget": SOURCE_BUDGET,
        "controls_share_decoder": True,
        "controls_share_source_budget": True,
        "decoder_executed": False,
        "cross_split_context_allowance_count": 0,
        "cross_split_context_allowance_granted": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }
