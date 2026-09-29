"""Necessary round-trip checks; neither full source equivalence nor proof.

The measured cycle's SUCCESS means that its stages ran.  Exact canonical IR
identity is a separate requirement.  The small source guards below identify
grammar that this adapter cannot yet preserve; they are not a general natural
language equivalence test or a list of approved legal texts.
"""
from __future__ import annotations

import re
from typing import Any


_CONDITION_LIST = re.compile(
    r"\b(?:if|unless)\s*(?:[—–:]|--?)\s*\(\s*(?:\d+|[A-Za-z])\s*\)", re.I,
)
_PARTICIPANT_LIST = re.compile(
    r"\bshall\s+be\s+made\s+by\s*(?:[—–:]|--?)\s*\(\s*[A-Za-z]\s*\)", re.I,
)
_NEGATIVE_CONSTRUCTION = re.compile(
    r"\bnothing\s+[^.!?;]{0,160}?\bshall\s+be\s+construed\s+to\s+"
    r"(?:authorize|permit|require)\b", re.I,
)
_LIST_CONTINUATION = re.compile(r"^\s*\(\s*(?:\d+|[A-Za-z])\s*\)")
_JOINED_PREDECESSOR = re.compile(r";\s*(?:and|or)\s*$", re.I)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_DANGLING_PURSUANT = re.compile(r"\bpursuant\s+to\s+(?:shall|must|may)\s+be\b", re.I)
_DANGLING_OF = re.compile(
    r"\bof\s*;\s*(?:and|or)\s*\(\s*(?:\d+|[A-Za-z])\s*\)", re.I,
)


def unsupported_source_grammar(text: str, *, preceding_text: str = "") -> list[str]:
    """Reject only identified v1 scope gaps, leaving ordinary if/or text alone.

    Enumerated condition and participant branches need a scoped representation;
    retaining words in an object atom is not evidence of that representation.
    A following list item split at a blank line still belongs to a predecessor
    ending in ``; and/or``.  Quoted labels are not grammatical control words.
    These guards can be retired only alongside support and regression evidence
    for the corresponding structure, not merely a changed parser surface.
    """
    surface = _QUOTED.sub(lambda match: " " * len(match.group()), text)
    predecessor = _QUOTED.sub(lambda match: " " * len(match.group()), preceding_text)
    reasons = []
    if _CONDITION_LIST.search(surface):
        reasons.append("unsupported_enumerated_condition_scope")
    elif (_LIST_CONTINUATION.search(surface) and _JOINED_PREDECESSOR.search(predecessor)
          and _CONDITION_LIST.search(predecessor)):
        reasons.append("unsupported_enumerated_condition_continuation")
    if _PARTICIPANT_LIST.search(surface):
        reasons.append("unsupported_enumerated_participant_scope")
    if _NEGATIVE_CONSTRUCTION.search(surface):
        reasons.append("unsupported_negative_interpretive_scope")
    # Observed source-ingest omissions, not a guess at the missing citation.
    # Requiring the following verb/list avoids treating month names or normal
    # references such as "pursuant to May 5 regulations" as missing targets.
    if _DANGLING_PURSUANT.search(surface) or _DANGLING_OF.search(surface):
        reasons.append("unresolved_source_cross_reference")
    return reasons


def canonical_cycle_integrity(result: Any) -> dict[str, Any]:
    """Compare the exact existing canonical payload, excluding no semantic field.

    Canonical IR CIDs cover every v1 rule field and canonical rule order, unlike
    stage/result CIDs which also include request and source identities.  This
    checks preservation of L1 by L2, not whether L1 captured the original law.
    """
    from ..legal_ir.canonical_contracts import CanonicalRoundTripIR, OperationStatus

    l1 = getattr(result, "l1_result", None)
    l2 = getattr(result, "l2_result", None)
    left = getattr(l1, "canonical_ir", None)
    right = getattr(l2, "canonical_ir", None)
    reasons = []
    if getattr(result, "status", None) != OperationStatus.SUCCESS:
        reasons.append("incomplete_canonical_cycle")
    if not isinstance(left, CanonicalRoundTripIR) or not isinstance(right, CanonicalRoundTripIR):
        reasons.append("missing_canonical_cycle_ir")
    elif left.ir_cid != right.ir_cid:
        reasons.append("canonical_cycle_ir_mismatch")
    if any(getattr(stage, "unsupported_semantics", ()) for stage in (l1, l2)):
        reasons.append("partial_canonical_cycle_semantics")
    return {
        "passed": not reasons, "reasons": reasons,
        "l1_ir_cid": left.ir_cid if isinstance(left, CanonicalRoundTripIR) else None,
        "l2_ir_cid": right.ir_cid if isinstance(right, CanonicalRoundTripIR) else None,
        "scope": "exact_canonical_ir_cycle_identity",
        "full_source_equivalence_proved": False, "admitted": False,
    }
