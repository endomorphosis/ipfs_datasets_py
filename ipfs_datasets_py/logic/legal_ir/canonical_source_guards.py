"""Bounded source-only warnings for one unresolved attributed-actor pattern.

This is a conservative English pattern guard, not a coreference resolver or a
semantic parser. A third-person deontic subject after two distinct named
participants requires clarification in the supported pattern. No match supplies
no general assurance about clarity, representability, or source fidelity.
Only the exact source is accepted; targets, vocabularies, and models are absent.
"""
from __future__ import annotations

import hashlib
import re

SCHEMA = "canonical-source-guard-analysis/v1"
IMPLEMENTATION_PROFILE = "source-only-attributed-pronoun-pattern/v1"
MAX_SOURCE_CHARS = 65_536
MAX_DIAGNOSTICS = 128

# Bound noun phrases to six lexical words. The pattern starts at a clause
# boundary and requires an explicit recipient and complementizer. It does not
# reject ordinary pronouns, direct norms, or quoted material generally.
_SPACE = r"[^\S\r\n]+"
_WORD = r"[^\W\d_][\w'’\-]*"
_PARTICIPANT = rf"{_WORD}(?:{_SPACE}{_WORD}){{0,5}}"
_REPORTING = (rf"(?:told|tells|informed|informs|notified|notifies|reminded|reminds|"
              rf"warned|warns|advised|advises|said{_SPACE}to|says{_SPACE}to|"
              rf"explained{_SPACE}to|explains{_SPACE}to)")
_MODAL = (rf"(?:must|shall|may|cannot|can{_SPACE}not|"
          rf"(?:is|are){_SPACE}(?:required|obligated|allowed|permitted){_SPACE}to|"
          rf"(?:is|are){_SPACE}prohibited{_SPACE}from)")
_ATTRIBUTED = re.compile(
    rf"(?:\A|(?<=[.!?;:,\n]))[^\S\r\n]*"
    rf"(?P<speaker>{_PARTICIPANT}){_SPACE}(?P<reporting>{_REPORTING}){_SPACE}"
    rf"(?P<recipient>{_PARTICIPANT}){_SPACE}that\s+"
    rf"(?P<pronoun>they|he|she){_SPACE}(?P<modal>{_MODAL})\b",
    re.IGNORECASE,
)
_PRONOUNS = frozenset({"i", "me", "we", "us", "you", "he", "him", "she", "her", "it", "they", "them"})
_CLAUSE_WORDS = frozenset({"that", "who", "whom", "which", "and", "or", "if", "unless"})


def _participant_identity(text: str) -> str | None:
    words = text.casefold().split()
    if words and words[0] in {"the", "a", "an"}:
        words = words[1:]
    if not words or any(word in _PRONOUNS | _CLAUSE_WORDS for word in words):
        return None
    return " ".join(words)


def _quoted_mask(text: str) -> bytearray:
    """Mask quoted spans without treating in-word apostrophes as delimiters.

    Ignoring a quoted pattern prevents metalinguistic examples becoming actor
    diagnoses. An unmatched opening quote is conservatively masked to the end;
    this helper does not attest that quotations themselves are well formed.
    """
    mask = bytearray(len(text))
    closing, start = None, None
    pairs = {'"': '"', "“": "”", "‘": "’", "'": "'"}
    for index, character in enumerate(text):
        if index and text[index - 1] == "\\":
            continue
        before = text[index - 1] if index else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if character in {"'", "’"} and before.isalnum() and after.isalnum():
            continue
        if closing is not None:
            if character == closing:
                mask[start:index + 1] = b"\x01" * (index + 1 - start)
                closing, start = None, None
        elif character in pairs and (character != "'" or not before.isalnum()):
            closing, start = pairs[character], index
    if closing is not None:
        mask[start:] = b"\x01" * (len(text) - start)
    return mask


def analyze_canonical_source(source_text: str) -> dict:
    """Diagnose a narrow competing-actor pattern from bounded exact source.

    Diagnostic ``start``/``end`` are half-open Unicode character offsets of the
    pronoun. ``competing_participants`` are exact source spans, not selected
    actors. Repeated participant labels and non-named/pronominal participants
    are outside this guard. More than 128 diagnoses fails instead of truncating.
    """
    if type(source_text) is not str or not source_text.strip() or len(source_text) > MAX_SOURCE_CHARS:
        raise ValueError("nonblank source text of at most 65536 characters required")
    try:
        source_bytes = source_text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("valid UTF-8 source text required") from error
    quoted = _quoted_mask(source_text)
    diagnostics = []
    for match in _ATTRIBUTED.finditer(source_text):
        if quoted[match.start("speaker")] or quoted[match.start("pronoun")]:
            continue
        speaker, recipient = match.group("speaker"), match.group("recipient")
        first, second = _participant_identity(speaker), _participant_identity(recipient)
        if first is None or second is None or first == second:
            continue
        pronoun = match.group("pronoun")
        diagnostics.append({
            "code": "source.unresolved_actor_pronoun",
            "message": (f"The attributed norm uses '{pronoun}' after distinct participants "
                        f"'{speaker}' and '{recipient}'. Name the obligated, permitted, or "
                        "prohibited actor explicitly before constructing a canonical rule."),
            "start": match.start("pronoun"), "end": match.end("pronoun"),
            "pronoun": pronoun, "competing_participants": [speaker, recipient],
            "reporting_clause_start": match.start("speaker"), "reporting_clause_end": match.end("modal"),
        })
        if len(diagnostics) > MAX_DIAGNOSTICS:
            raise ValueError("source guard diagnostic count exceeds bound; no truncation performed")
    required = bool(diagnostics)
    return {"schema": SCHEMA, "implementation_profile": IMPLEMENTATION_PROFILE,
            "status": "clarification_required" if required else "no_guard_triggered",
            "requires_clarification": required, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_characters": len(source_text), "diagnostics": diagnostics,
            "model_calls": 0, "qualified": False}


__all__ = ["analyze_canonical_source"]
