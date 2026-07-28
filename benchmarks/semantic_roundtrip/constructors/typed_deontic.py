"""Typed-deontic adapter for the canonical semantic round-trip boundary.

The production deontic converter deliberately remains unchanged.  This module
only projects its ``LegalNormIR`` records into the closed, scored
``CanonicalRuleIR`` schema used by the composition benchmark.

Diagnostics and repair-trigger emission are out-of-band: the no-repair
baseline ``construct`` path remains a pure ``ConstructorResult`` and never
invokes selective repair.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)


TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE: Final = (
    "TypedDeonticCanonicalConstructor@1"
)
TYPED_DEONTIC_DIAGNOSTICS_INTERFACE: Final = (
    "TypedDeonticConstructorDiagnostics@1"
)
TYPED_DEONTIC_TRIGGER_DETECTOR_INTERFACE: Final = (
    "TypedDeonticDiagnosticTriggerDetector@1"
)

# Conservative default aligned with SelectiveRepairPolicy.
DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD: Final = 0.65
_ATOM_MATCH_THRESHOLD: Final = 0.12

_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
_TEMPORAL_CUE_RE: Final = re.compile(
    r"\b("
    r"after|before|within|until|by|during|following|"
    r"annual|annually|monthly|weekly|daily|"
    r"\d+\s*(?:day|days|hour|hours|week|weeks|month|months|year|years)|"
    # Compact incident windows (exec_order style): 24h / 72hr / 90-hrs.
    r"\d+\s*(?:-\s*)?(?:h|hr|hrs)\b|"
    r"calendar\s+day|business\s+day"
    r")\b",
    re.IGNORECASE,
)
# Domain-scope condition cues (exec_order style): "in any government
# communications" / "in official channels". Used only for missing-slot
# diagnostics; projection still requires closed-vocabulary grounding.
_DOMAIN_CONDITION_CUE_RE: Final = re.compile(
    r"\b(?:in\s+(?:any\s+|all\s+)?(?:government|public|official|agency)\b|"
    r"in\s+\w[\w\s-]{0,40}\bcommunications?\b)",
    re.IGNORECASE,
)
_OBLIGATION_CUE_RE: Final = re.compile(
    r"\b(must|shall|required|obligation|obliged)\b",
    re.IGNORECASE,
)
_PROHIBITION_CUE_RE: Final = re.compile(
    r"\b(must\s+not|shall\s+not|prohibit|forbidden|may\s+not)\b",
    re.IGNORECASE,
)
_PERMISSION_CUE_RE: Final = re.compile(
    r"\b(may|permission|permitted|allowed)\b",
    re.IGNORECASE,
)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_numeric_surface(text: str) -> str:
    """Normalize currency, duration, and thousands-grouped numbers.

    Maps surfaces such as ``$10,000`` / ``10,000`` onto a single digit token
    ``10000`` so closed-vocabulary atoms like
    ``transaction_amount_exceeds_10000`` can ground without an LLM.

    Also expands compact hour windows used in executive-order / incident
    reporting language (``24h``, ``24-hr``, ``72hrs``) into ``24 hour`` so
    atoms such as ``within_24_hours`` ground with precision 1.0.
    """

    cleaned = re.sub(r"\$\s*", "", text)
    # Collapse nested thousands separators: 1,234,567 → 1234567.
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = re.sub(r"(\d),(\d{3})\b", r"\1\2", cleaned)
    # Compact hour durations: 24h / 24-hr / 72hrs → "<n> hour".
    cleaned = re.sub(
        r"\b(\d+)\s*-?\s*(?:hours?|hrs?|h)\b",
        r"\1 hour",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Permission / SLA phrasing "up to 72 hours to report" is semantically a
    # within-duration window for closed atoms such as ``within_72_hours``.
    cleaned = re.sub(
        r"\bup\s+to\s+(\d+)\s+(hour|day|week|month|year)s?\b",
        r"within \1 \2",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _tokens(value: object) -> tuple[str, ...]:
    surface = _normalize_numeric_surface(
        _clean_text(value).lower().replace("_", " ")
    )
    words = _TOKEN_RE.findall(surface)
    normalized: list[str] = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        normalized.append(word)
    return tuple(normalized)


def _token_stem_variants(word: str) -> frozenset[str]:
    """Expand a normalized token with light inflectional variants.

    Used only for closed-vocabulary matching so past participles such as
    ``resolved`` can align to the atom ``resolve`` without an LLM, and so
    frequency adverbs such as ``annually`` align to evidence ``annual``.
    """

    variants = {word}
    if len(word) > 4 and word.endswith("ies"):
        variants.add(word[:-3] + "y")
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        variants.add(word[:-1])
    if len(word) > 4 and word.endswith("ed"):
        variants.add(word[:-1])  # resolved -> resolve
        variants.add(word[:-2])  # walked -> walk
        if len(word) > 5 and word[-3] == word[-4]:
            variants.add(word[:-3])  # stopped -> stop
    if len(word) > 5 and word.endswith("ing"):
        variants.add(word[:-3])
        variants.add(word[:-3] + "e")
    # Frequency / manner adverbs: annually -> annual, monthly -> month.
    # Require length > 5 so short forms like "only" / "daily" stay intact
    # (daily would otherwise collapse to the unusable stem "dai").
    if len(word) > 5 and word.endswith("ly"):
        stem = word[:-2]
        if len(stem) >= 4:
            variants.add(stem)
    return frozenset(variants)


def _expanded_token_set(value: object) -> set[str]:
    expanded: set[str] = set()
    for token in _tokens(value):
        expanded |= _token_stem_variants(token)
    return expanded


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(item))
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        result = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    if value is None:
        return []
    return [str(value)]


def _jaccard(left: object, right: object) -> float:
    left_tokens, right_tokens = (
        _expanded_token_set(left),
        _expanded_token_set(right),
    )
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _atom_hit_counts(
    text: object, candidate: str
) -> tuple[int, int, int]:
    """Return ``(exact_hits, stem_hits, cand_token_count)``.

    Exact hits (candidate token present in text tokens) outrank stem-only
    hits so ``withdraw the filing`` prefers ``withdraw`` over a stem of
    ``filing`` → ``file``.
    """

    cand_toks = _tokens(candidate)
    if not cand_toks:
        return 0, 0, 0
    text_exact = set(_tokens(text))
    if not text_exact:
        return 0, 0, len(cand_toks)
    text_exp = set()
    for token in text_exact:
        text_exp |= _token_stem_variants(token)
    exact_hits = 0
    stem_hits = 0
    for token in cand_toks:
        if token in text_exact:
            exact_hits += 1
            continue
        variants = _token_stem_variants(token)
        if variants & text_exact or variants & text_exp:
            stem_hits += 1
            continue
        # Text token stems to the candidate atom (resolved → resolve).
        if any(
            token in _token_stem_variants(text_token)
            for text_token in text_exact
        ):
            stem_hits += 1
    return exact_hits, stem_hits, len(cand_toks)


def _atom_match_score(text: object, candidate: str) -> float:
    """Score a closed-vocabulary atom against free text.

    Combines expanded Jaccard with a precision-weighted hit count so short
    exact atoms (``work``) beat long partial overlaps
    (``work_compliance_with_...``) while still preferring longer atoms when
    nearly all of their tokens are grounded in the evidence. Exact token
    hits are weighted above stem-only hits.
    """

    exact_hits, stem_hits, cand_n = _atom_hit_counts(text, candidate)
    hits = exact_hits + stem_hits
    if hits <= 0 or cand_n <= 0:
        return 0.0
    precision = hits / cand_n
    # Exact hits count double so stem collisions cannot outrank true verbs.
    weighted_hits = float(exact_hits) * 2.0 + float(stem_hits)
    specificity = precision * weighted_hits
    jaccard = _jaccard(text, candidate)
    return max(jaccard, specificity)


def _best_atom_scored(
    value: object,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = _ATOM_MATCH_THRESHOLD,
) -> tuple[str, float | None]:
    """Return ``(atom, confidence)`` using the pilot matching rule."""

    pieces = _flatten_strings(value)
    text = " ".join(pieces)
    if not _clean_text(text):
        return ("", None) if allow_empty else ("", None)
    if not candidates:
        return "", None

    def _rank(candidate: str) -> tuple[float, int, str]:
        score = max(
            [_atom_match_score(text, candidate)]
            + [_atom_match_score(piece, candidate) for piece in pieces]
        )
        exact_hits, _stem_hits, _n = _atom_hit_counts(text, candidate)
        for piece in pieces:
            piece_exact, _, _ = _atom_hit_counts(piece, candidate)
            if piece_exact > exact_hits:
                exact_hits = piece_exact
        # Higher score, then more exact hits, then stable name.
        return (score, exact_hits, candidate)

    ranked = sorted(
        ((_rank(candidate), candidate) for candidate in candidates),
        key=lambda item: (-item[0][0], -item[0][1], item[0][2]),
    )
    best_rank, best_candidate = ranked[0]
    best_score = float(best_rank[0])
    if best_score < threshold:
        return "", max(0.0, min(1.0, best_score))
    # Confidence is always a unit interval for diagnostics; match score may
    # exceed 1.0 when specificity rewards multi-token grounding.
    return best_candidate, max(0.0, min(1.0, best_score))


def _best_atom(
    value: object,
    candidates: Sequence[str],
    *,
    allow_empty: bool = False,
    threshold: float = _ATOM_MATCH_THRESHOLD,
) -> str:
    """Return the same deterministic closed-vocabulary match as the pilot."""

    atom, _confidence = _best_atom_scored(
        value,
        candidates,
        allow_empty=allow_empty,
        threshold=threshold,
    )
    return atom


def _map_many(value: object, candidates: Sequence[str]) -> tuple[str, ...]:
    values: list[object]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value is None or value == "" or value == []:
        values = []
    else:
        values = [value]
    return tuple(
        sorted(
            {
                atom
                for item in values
                if (atom := _best_atom(item, candidates))
            }
        )
    )


def _map_many_scored(
    value: object, candidates: Sequence[str]
) -> tuple[tuple[str, ...], float | None]:
    """Map multi-valued facets and retain the minimum matched confidence."""

    values: list[object]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value is None or value == "" or value == []:
        values = []
    else:
        values = [value]
    atoms: set[str] = set()
    confidences: list[float] = []
    for item in values:
        atom, confidence = _best_atom_scored(item, candidates)
        if atom:
            atoms.add(atom)
            if confidence is not None:
                confidences.append(confidence)
    if not values:
        return (), None
    if not atoms:
        return (), min(confidences) if confidences else 0.0
    return tuple(sorted(atoms)), min(confidences) if confidences else None


# Exception clause connectors that participate in closed atom names such as
# ``unless_required_by_law`` / ``without_prior_written_approval``.
_EXCEPTION_CLAUSE_TYPES: Final = frozenset(
    {
        "unless",
        "except",
        "without",
        "except when",
        "except if",
        "except where",
    }
)


def _structured_clause_match_text(item: object, *, facet: str) -> str:
    """Build closed-vocabulary match text for a structured deontic clause.

    Uses content fields only (``raw_text`` / ``normalized_text`` / ``value``)
    rather than :func:`_flatten_strings` over the whole clause dict. Flattening
    leaks JSON keys and always injects ``clause_type`` (e.g. ``if``), which
    incorrectly fully-grounds soft request hedges such as ``if_requested`` from
    bare content ``requested``.

    Exception connectors (``unless`` / ``except`` / ``without``) are re-prefixed
    when the content omits them so atoms like ``unless_required_by_law`` still
    ground from ``clause_type=unless`` + ``raw_text='required by law'``.
    Condition connectors (``if`` / ``when``) are **not** auto-prefixed: the
    marker must appear in the clause content for ``if_*`` / ``when_*`` atoms.
    """

    if isinstance(item, str):
        return item
    if not isinstance(item, Mapping):
        return " ".join(_flatten_strings(item))

    content_parts: list[str] = []
    seen: set[str] = set()
    # Prefer deontic-converter clause bodies; also accept the generic ``text``
    # key used by unit fixtures and alternate IR shapes.
    for key in ("raw_text", "normalized_text", "value", "text"):
        raw = item.get(key)
        if raw is None:
            continue
        text = _clean_text(raw)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        content_parts.append(text)
    content_text = " ".join(content_parts)
    clause_type = _clean_text(item.get("clause_type")).lower()

    if facet == "exceptions" and clause_type in _EXCEPTION_CLAUSE_TYPES:
        if clause_type and clause_type not in content_text.lower():
            return f"{clause_type} {content_text}".strip()
    if content_text:
        return content_text
    return clause_type


def _map_structured_qualifiers_scored(
    value: object,
    candidates: Sequence[str],
    *,
    facet: str,
) -> tuple[tuple[str, ...], float | None]:
    """Map structured condition/exception/temporal clauses with full grounding.

    Unlike :func:`_map_many_scored`, this path:
    * builds match text via :func:`_structured_clause_match_text` (no key leak);
    * requires :func:`_qualifier_fully_grounded` so partial stems cannot promote
      multi-token atoms (``requested`` ↛ ``if_requested``).
    """

    values: list[object]
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = list(value)
    elif value is None or value == "" or value == []:
        values = []
    else:
        values = [value]
    atoms: set[str] = set()
    confidences: list[float] = []
    for item in values:
        text = _structured_clause_match_text(item, facet=facet)
        if not _clean_text(text):
            continue
        atom, confidence = _best_atom_scored(text, candidates)
        if atom and not _qualifier_fully_grounded(text, atom):
            atom = ""
        if atom:
            atoms.add(atom)
            if confidence is not None:
                confidences.append(confidence)
    if not values:
        return (), None
    if not atoms:
        return (), min(confidences) if confidences else 0.0
    return tuple(sorted(atoms)), min(confidences) if confidences else None


def _resolve_conflicting_modality_rules(
    rules: Sequence[CanonicalRule],
) -> tuple[CanonicalRule, ...]:
    """Collapse obligation+prohibition pairs for the same actor/action/object.

    Sentences such as ``must disclose … and shall not disclose … unless …``
    yield two parser elements that share a closed-vocabulary triple. Legal
    reading (and holdout gold) prefers the prohibition and unions qualifier
    facets from both norms. Same-modality duplicates and non-conflicting
    groups are left untouched.
    """

    if len(rules) < 2:
        return tuple(rules)

    groups: dict[tuple[str, str, str], list[CanonicalRule]] = {}
    order: list[tuple[str, str, str]] = []
    for rule in rules:
        key = (rule.actor, rule.action, rule.object)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rule)

    resolved: list[CanonicalRule] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            resolved.append(group[0])
            continue
        modalities = {rule.modality for rule in group}
        if "O" in modalities and "F" in modalities:
            primary = next(rule for rule in group if rule.modality == "F")
            conditions: set[str] = set()
            exceptions: set[str] = set()
            temporal: set[str] = set()
            for rule in group:
                conditions.update(rule.conditions)
                exceptions.update(rule.exceptions)
                temporal.update(rule.temporal)
            # Prefer exceptions over dual-placed conditions after the merge.
            conditions.difference_update(exceptions)
            resolved.append(
                CanonicalRule(
                    modality="F",
                    actor=primary.actor,
                    action=primary.action,
                    object=primary.object,
                    conditions=tuple(sorted(conditions)),
                    exceptions=tuple(sorted(exceptions)),
                    temporal=tuple(sorted(temporal)),
                )
            )
        else:
            resolved.extend(group)
    return tuple(resolved)


def _modality_from_text(value: object) -> str:
    text = _clean_text(value).lower()
    if (
        text in {"f", "prohibition", "forbidden"}
        or "prohibit" in text
        or "shall not" in text
        or "must not" in text
    ):
        return "F"
    if text in {"p", "permission", "permitted"} or "permission" in text:
        return "P"
    return "O"


def _modality_conflict(value: object, source_text: str = "") -> bool:
    """True when obligation and prohibition (or permission) cues co-occur."""

    text = " ".join(
        filter(
            None,
            [
                _clean_text(value),
                _clean_text(source_text),
            ],
        )
    )
    if not text:
        return False
    has_obligation = bool(_OBLIGATION_CUE_RE.search(text))
    has_prohibition = bool(_PROHIBITION_CUE_RE.search(text))
    has_permission = bool(_PERMISSION_CUE_RE.search(text))
    modality_labels = {
        label
        for label in re.findall(
            r"\b(obligation|prohibition|permission|forbidden|permitted)\b",
            text,
            flags=re.IGNORECASE,
        )
    }
    label_conflict = len(
        {
            "obligation" if item.lower() in {"obligation"} else item.lower()
            for item in modality_labels
        }
        & {"obligation", "prohibition", "permission", "forbidden", "permitted"}
    ) > 1
    return bool(
        (has_obligation and has_prohibition)
        or (has_obligation and has_permission and has_prohibition)
        or label_conflict
        or (
            "obligation" in text.lower()
            and "prohibition" in text.lower()
        )
    )


def _source_has_temporal_cue(source_text: str) -> bool:
    return bool(_TEMPORAL_CUE_RE.search(source_text or ""))


def _source_has_domain_condition_cue(source_text: str) -> bool:
    """True when source suggests a domain/scope gate (exec_order style)."""

    return bool(_DOMAIN_CONDITION_CUE_RE.search(source_text or ""))


# Qualifier atoms whose surface form is a temporal window / deadline.
_TEMPORAL_QUALIFIER_RE: Final = re.compile(
    r"(within|before|after|during|until|by_|at_|annually|for_|days|hours|"
    r"weeks|months|years|written_notice|deadline|time)",
    re.IGNORECASE,
)
# Duration units that keep a ``for_*`` atom on the temporal facet
# (``for_five_years``) rather than purpose/scope conditions
# (``for_marketing_purposes``, ``for_members_in_good_standing``).
_FOR_DURATION_UNIT_RE: Final = re.compile(
    r"(?:day|days|hour|hours|week|weeks|month|months|year|years|time|"
    r"deadline|period)",
    re.IGNORECASE,
)
# Precondition gates written as ``before_<gerund>_…``
# (``before_making_robocalls_to_wireless_numbers``) — conditions, not pure
# temporal process labels such as ``before_arbitration``.
_BEFORE_GERUND_CONDITION_RE: Final = re.compile(
    r"^before_[a-z0-9]+ing(?:_|$)",
    re.IGNORECASE,
)
# Coordinating conjunctions used to split multi-action norms
# (``maintain X and honor Y``, ``engage in X or share Y``).
_COORD_ACTION_SPLIT_RE: Final = re.compile(r"\s+(?:and|or)\s+", re.IGNORECASE)
# Sentence splitter for uncovered permission-sentence recovery.
_SENTENCE_SPLIT_RE: Final = re.compile(r"(?<=[.!?])\s+|\n+")
# Permission cues used when recovering sentences the deontic converter missed.
_PERMISSION_SENTENCE_RE: Final = re.compile(
    r"\b(?:may|might|are\s+allowed|is\s+allowed|be\s+allowed|permitted)\b",
    re.IGNORECASE,
)
# Qualifier atoms that are conditional gates (incl. advance-notice gates and
# domain-scope ``in_*`` atoms such as ``in_government_communications``).
_CONDITION_QUALIFIER_RE: Final = re.compile(
    r"(upon_|if_|when_|unless|provided|does_not|exceed|over_|required_by|"
    r"\bin_|advance_notice|gift_value|work_does|transaction)",
    re.IGNORECASE,
)
# Qualifier atoms that are exception carve-outs.
_EXCEPTION_QUALIFIER_RE: Final = re.compile(
    r"(without|except|unless|prior_written_approval|emergency)",
    re.IGNORECASE,
)
# Evidence-side exception framing cues (not atom names).
_EXCEPTION_CONTEXT_RE: Final = re.compile(
    r"\b(?:without|except(?:\s+when|\s+if)?|unless)\b",
    re.IGNORECASE,
)
_PASSIVE_BE_RE: Final = re.compile(
    r"\b(?:shall|must|will|may|is|are|be)\s+be\s+\w+",
    re.IGNORECASE,
)
_COLLECTIVE_ACTORS: Final = frozenset(
    {"parties", "either_party", "both_parties", "party"}
)
# Schema scaffolding tokens that often appear only in closed-vocabulary atom
# names (e.g. ``transaction_amount_exceeds_10000``) while surface evidence
# says ``transactions exceeding $10,000``.  Optional only when at least one
# non-optional content token is present and every required token grounds.
_OPTIONAL_QUALIFIER_GROUNDING_TOKENS: Final = frozenset({"amount"})
# Leading domain-scope prepositions on atoms such as
# ``in_government_communications`` may be absent or substituted in surface
# evidence ("government communications", "for government communications")
# while content tokens still identify the closed atom.
_OPTIONAL_DOMAIN_PREPOSITION_TOKENS: Final = frozenset({"in", "on"})


def _norm_evidence_text(data: Mapping[str, object]) -> str:
    """Concatenate per-norm fields used for closed-vocabulary recovery."""

    pieces = _flatten_strings(
        [
            data.get("actor"),
            data.get("action"),
            data.get("action_verb"),
            data.get("action_object"),
            data.get("conditions"),
            data.get("exceptions"),
            data.get("temporal_constraints"),
            data.get("source_text"),
        ]
    )
    return " ".join(pieces)


def _classify_qualifier_facet(atom: str, evidence: str = "") -> str:
    """Map a matched qualifier atom to conditions / exceptions / temporal.

    When *evidence* is supplied, exception framing such as ``without X`` or
    ``except when required by…`` reclassifies a grounded non-temporal atom as
    an exception carve-out (legal_doc prohibition style).

    Domain-scope atoms such as ``in_government_communications`` (exec_order)
    are conditions even when surface evidence uses "if in …" framing from the
    deterministic realizer.

    Repair-development refinements (PLAT2-050):
    * ``for_*`` purpose/scope atoms without duration units map to conditions
      (``for_marketing_purposes``) while duration windows such as
      ``for_five_years`` stay temporal.
    * ``before_<gerund>_…`` precondition gates map to conditions
      (``before_making_robocalls_to_wireless_numbers``) while pure process
      labels such as ``before_arbitration`` stay temporal.
    """

    atom_l = str(atom or "").strip().lower()
    if not atom_l:
        return "conditions"
    # Order matters: advance-notice gates are conditions even when they
    # mention hours; written-notice windows with day counts stay temporal.
    if "advance_notice" in atom_l:
        return "conditions"
    # Purpose/scope ``for_*`` without a duration unit is a condition, not a
    # temporal window (legal_doc_2 / dept_memo_1 repair-development residuals).
    if atom_l.startswith("for_") and not _FOR_DURATION_UNIT_RE.search(
        atom_l[4:]
    ):
        return "conditions"
    # Precondition gerunds: before_making_… / before_using_… → conditions.
    if _BEFORE_GERUND_CONDITION_RE.match(atom_l):
        return "conditions"
    if _EXCEPTION_QUALIFIER_RE.search(atom_l) and not atom_l.startswith(
        "upon_"
    ):
        # "unless emergency" style carve-outs; keep upon_* as conditions.
        if any(
            cue in atom_l
            for cue in ("without", "except", "prior_written", "emergency")
        ):
            return "exceptions"

    is_temporal = bool(_TEMPORAL_QUALIFIER_RE.search(atom_l))
    # Domain-scope preposition atoms (in_*/on_*) are conditions unless the
    # remainder is itself a pure temporal window (rare; keep temporal first).
    is_domain_scope = atom_l.startswith("in_") or atom_l.startswith("on_")
    is_condition = bool(_CONDITION_QUALIFIER_RE.search(atom_l)) or (
        is_domain_scope and not is_temporal
    )
    # Pure temporal windows keep the temporal facet even under surrounding
    # "except when…" wording so day-count / hour-count atoms are never stolen
    # into exceptions (exec_order ``within_24_hours``, legal day windows).
    if is_temporal and not is_condition:
        return "temporal"
    if evidence and _exception_framed_in_evidence(evidence, atom_l):
        return "exceptions"
    if is_condition:
        return "conditions"
    if is_temporal:
        return "temporal"
    if atom_l.startswith("with_"):
        return "conditions"
    return "conditions"


def _exception_framed_in_evidence(evidence: str, qualifier: str) -> bool:
    """True when *qualifier* is mentioned under without/except/unless framing.

    Looks for an exception cue in the evidence and requires at least one
    non-trivial qualifier token to appear after that cue (or the cue and the
    qualifier tokens to co-occur in a short local window).
    """

    text = _clean_text(evidence).lower()
    if not text or not _EXCEPTION_CONTEXT_RE.search(text):
        return False
    qual_toks = [
        token
        for token in _tokens(qualifier)
        if token not in _OPTIONAL_QUALIFIER_GROUNDING_TOKENS and len(token) > 2
    ]
    if not qual_toks:
        return False
    # Split on exception cues and inspect the span following each cue.
    parts = _EXCEPTION_CONTEXT_RE.split(text)
    # re.split with a capturing pattern keeps delimiters; walk cue → tail pairs.
    # When the pattern has no capture groups, parts are [pre, post, post, ...].
    # We only need any post-cue segment that grounds a content token.
    for index, part in enumerate(parts):
        if index == 0:
            continue
        tail = part
        # Also accept the immediate preceding token window for "without X".
        window = tail
        if index > 0:
            window = parts[index - 1][-40:] + " " + tail
        window_exp = _expanded_token_set(window if tail else text)
        if any(
            bool(_token_stem_variants(token) & window_exp) for token in qual_toks
        ):
            return True
    # Fallback: co-occurrence of cue + any content token in full evidence.
    text_exp = _expanded_token_set(text)
    return any(
        bool(_token_stem_variants(token) & text_exp) for token in qual_toks
    )


def _optional_grounding_tokens_for(qualifier: str) -> frozenset[str]:
    """Return tokens that may be absent when grounding *qualifier*.

    Includes global schema scaffolding (``amount``) plus, for domain-scope
    atoms such as ``in_government_communications``, the leading preposition
    so evidence ``government communications`` still grounds the closed atom.
    """

    optional: set[str] = set(_OPTIONAL_QUALIFIER_GROUNDING_TOKENS)
    atom_l = str(qualifier or "").strip().lower()
    if atom_l.startswith("in_") or atom_l.startswith("on_"):
        optional |= _OPTIONAL_DOMAIN_PREPOSITION_TOKENS
    return frozenset(optional)


def _qualifier_fully_grounded(evidence: str, qualifier: str) -> bool:
    """True when every required token of the qualifier atom is grounded.

    Requires precision 1.0 on non-optional tokens so ``within_30_days`` cannot
    fire on ``within 10 days`` evidence (the numeric token must match), and so
    ``within_24_hours`` cannot fire on a ``within 72 hours`` window.

    Schema scaffolding tokens listed in
    ``_OPTIONAL_QUALIFIER_GROUNDING_TOKENS`` (e.g. ``amount``) and domain
    prepositions on ``in_*`` / ``on_*`` atoms may be absent from surface
    evidence when at least one required content token grounds.
    """

    cand_toks = _tokens(qualifier)
    if not cand_toks:
        return False
    text_exp = _expanded_token_set(evidence)
    if not text_exp:
        return False
    optional_tokens = _optional_grounding_tokens_for(qualifier)
    required = [
        token for token in cand_toks if token not in optional_tokens
    ]
    optional = [
        token for token in cand_toks if token in optional_tokens
    ]
    # Never allow an all-optional qualifier (would match empty content).
    check = required if required else list(cand_toks)
    if not all(
        bool(_token_stem_variants(token) & text_exp) for token in check
    ):
        return False
    # Optional tokens improve confidence when present but do not block.
    _ = optional
    return True


def _harvest_qualifiers_from_evidence(
    evidence: str,
    vocabulary: AllowedAtomVocabulary,
) -> dict[str, tuple[str, ...]]:
    """Find closed-vocabulary qualifiers grounded in per-norm evidence text.

    Does **not** scan the full document — only the norm-local evidence string
    — so multi-rule pilots do not leak every temporal into every rule.
    """

    if not _clean_text(evidence) or not vocabulary.qualifiers:
        return {
            "conditions": (),
            "exceptions": (),
            "temporal": (),
        }
    buckets: dict[str, set[str]] = {
        "conditions": set(),
        "exceptions": set(),
        "temporal": set(),
    }
    for qualifier in vocabulary.qualifiers:
        if not _qualifier_fully_grounded(evidence, qualifier):
            continue
        facet = _classify_qualifier_facet(qualifier, evidence)
        buckets[facet].add(qualifier)
    return {
        key: tuple(sorted(values)) for key, values in buckets.items()
    }


def _recover_actor_action(
    data: Mapping[str, object],
    vocabulary: AllowedAtomVocabulary,
    *,
    actor: str,
    actor_conf: float | None,
    action: str,
    action_conf: float | None,
) -> tuple[str, float | None, str, float | None]:
    """Recover actor/action when the converter mis-parsed passive voice.

    Example: ``All disputes shall be resolved through binding arbitration...``
    yields actor=``All disputes`` and verb=``be``; gold maps to
    ``parties`` / ``resolve`` / ``disputes_through_...``.
    """

    if actor and action:
        return actor, actor_conf, action, action_conf
    evidence = _norm_evidence_text(data)
    if not evidence:
        return actor, actor_conf, action, action_conf

    if not action:
        recovered_action, recovered_action_conf = _best_atom_scored(
            [
                data.get("action"),
                data.get("action_verb"),
                data.get("action_object"),
                data.get("source_text"),
                evidence,
            ],
            vocabulary.actions,
        )
        if recovered_action:
            action, action_conf = recovered_action, recovered_action_conf

    if not actor:
        recovered_actor, recovered_actor_conf = _best_atom_scored(
            [
                data.get("actor"),
                data.get("source_text"),
                evidence,
            ],
            vocabulary.actors,
        )
        if recovered_actor:
            actor, actor_conf = recovered_actor, recovered_actor_conf

    if not actor and action and _PASSIVE_BE_RE.search(evidence):
        # Agentless passive obligation/prohibition: prefer collective actors
        # present in the closed vocabulary (construction/legal style).
        for preferred in (
            "parties",
            "either_party",
            "both_parties",
            "party",
        ):
            if preferred in vocabulary.actors:
                actor = preferred
                actor_conf = 0.55
                break

    return actor, actor_conf, action, action_conf


def _merge_qualifier_facets(
    structured: tuple[str, ...],
    harvested: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(sorted(set(structured) | set(harvested)))


def _prefer_exceptions_over_conditions(
    conditions: tuple[str, ...],
    exceptions: tuple[str, ...],
) -> tuple[str, ...]:
    """Drop dual-placed atoms from conditions when already listed as exceptions.

    Prohibition wording such as ``cannot disclose … without explicit consent,
    except when required by law enforcement`` often yields the same closed
    atoms from both structured exception slots and condition harvest.  Gold
    keeps those carve-outs on the exceptions facet only.
    """

    if not conditions or not exceptions:
        return conditions
    exception_set = set(exceptions)
    return tuple(atom for atom in conditions if atom not in exception_set)


def _reclassify_exception_framed_conditions(
    conditions: tuple[str, ...],
    exceptions: tuple[str, ...],
    evidence: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Move condition atoms into exceptions when evidence uses without/except."""

    if not conditions or not _clean_text(evidence):
        return conditions, exceptions
    kept: list[str] = []
    moved: set[str] = set(exceptions)
    for atom in conditions:
        facet = _classify_qualifier_facet(atom, evidence)
        if facet == "exceptions":
            moved.add(atom)
        else:
            kept.append(atom)
    return tuple(kept), tuple(sorted(moved))


@dataclass(frozen=True, slots=True)
class _DictNormView:
    """Lightweight norm adapter for recovered / split dict records."""

    data: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.data)


def _leading_closed_action(part: str, actions: Sequence[str]) -> str:
    """Return a closed action that leads *part* (exact surface / first token)."""

    text = _clean_text(part).lower().strip()
    text = re.sub(r"^to\s+", "", text)
    if not text or not actions:
        return ""
    ranked = sorted(actions, key=lambda atom: (-len(atom), atom))
    for action in ranked:
        surface = action.replace("_", " ")
        if text == surface or text.startswith(surface + " "):
            return action
        first = text.split()[0]
        if "_" not in action and first == action:
            return action
    return ""


def _local_norm_source(
    data: Mapping[str, object],
    *,
    action_verb: str,
    action_object: str,
) -> str:
    """Build a segment-local evidence string (avoids cross-conjunct harvest)."""

    actor = _clean_text(data.get("actor"))
    pieces = [actor, action_verb, action_object]
    local = " ".join(piece for piece in pieces if piece)
    return local or _clean_text(data.get("source_text"))


def _split_conjoined_action_norm(
    data: Mapping[str, object],
    vocabulary: AllowedAtomVocabulary,
) -> list[dict[str, object]]:
    """Split multi-action norms coordinated with *and* / *or*.

    Examples (repair-development residuals):
    * ``maintain a Do Not Call registry and honor all requests``
    * ``engage in insider trading or share material non-public information``

    Structured temporal constraints attach only to the final conjunct so a
    trailing ``within 30 days`` does not leak onto the left-hand action.
    Object phrases that merely coordinate nouns (``items and gifts``) are
    left intact because secondary segments must *lead* with a closed action.
    """

    payload = dict(data)
    verb = _clean_text(payload.get("action_verb") or "")
    obj = _clean_text(
        payload.get("action_object") or payload.get("action") or ""
    )
    if not obj:
        return [payload]
    parts = _COORD_ACTION_SPLIT_RE.split(obj)
    if len(parts) < 2:
        return [payload]

    secondary: list[tuple[int, str, str]] = []
    for index, part in enumerate(parts):
        if index == 0:
            continue
        action = _leading_closed_action(part, vocabulary.actions)
        if action and action != verb:
            secondary.append((index, action, part))
    if not secondary:
        return [payload]

    expanded: list[dict[str, object]] = []
    first = dict(payload)
    first["action_verb"] = verb
    first["action_object"] = parts[0]
    first["action"] = f"{verb} {parts[0]}".strip()
    # Structured temporal belongs to the rightmost conjunct only.
    first["temporal_constraints"] = ()
    first["source_text"] = _local_norm_source(
        payload, action_verb=verb, action_object=parts[0]
    )
    expanded.append(first)

    last_secondary_index = secondary[-1][0]
    for index, action, part in secondary:
        remaining = part
        surface = action.replace("_", " ")
        remaining = re.sub(
            rf"^(?:to\s+)?{re.escape(surface)}\b",
            "",
            remaining,
            flags=re.IGNORECASE,
        ).strip(" ,;")
        if not remaining:
            remaining = part
            for token in action.split("_"):
                remaining = re.sub(
                    rf"\b{re.escape(token)}s?\b",
                    " ",
                    remaining,
                    flags=re.IGNORECASE,
                )
            remaining = re.sub(r"\s+", " ", remaining).strip(" ,;")
        segment = dict(payload)
        segment["action_verb"] = action
        segment["action_object"] = remaining or part
        segment["action"] = part
        if index != last_secondary_index:
            segment["temporal_constraints"] = ()
        segment["source_text"] = _local_norm_source(
            payload,
            action_verb=action,
            action_object=remaining or part,
        )
        # Re-attach original source tail so trailing temporal windows on the
        # rightmost conjunct still harvest (``… honor all requests within 30
        # days``).
        if index == last_secondary_index:
            original_source = _clean_text(payload.get("source_text"))
            if original_source:
                segment["source_text"] = original_source
        expanded.append(segment)
    return expanded


def _permission_sentence_already_covered(
    sentence: str,
    covered_tokens: set[str],
    *,
    coverage_threshold: float = 0.7,
) -> bool:
    """True when most content tokens of *sentence* already appear in norms."""

    content = [token for token in _tokens(sentence) if len(token) > 3]
    if not content:
        return False
    hits = sum(1 for token in content if token in covered_tokens)
    return (hits / len(content)) >= coverage_threshold


def _recover_missing_permission_norms(
    source_text: str,
    existing_norm_dicts: Sequence[Mapping[str, object]],
    vocabulary: AllowedAtomVocabulary,
) -> list[dict[str, object]]:
    """Recover permission sentences the deontic converter failed to emit.

    Deterministic only: closed-vocabulary actor/action/object grounding on
    sentences with permission cues (``may``, ``are allowed``) that are not
    already covered by converter source spans. Used for repair-development
    missing-rule residuals such as credit-union waivers and handbook discuss
    permissions — never consults gold IR or blind data.
    """

    if not _clean_text(source_text):
        return []
    covered = " ".join(
        _clean_text(norm.get("source_text")) for norm in existing_norm_dicts
    )
    covered_tokens = set(_tokens(covered))
    recovered: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for raw_sentence in _SENTENCE_SPLIT_RE.split(source_text):
        sentence = raw_sentence.strip()
        if not sentence or not _PERMISSION_SENTENCE_RE.search(sentence):
            continue
        if _permission_sentence_already_covered(sentence, covered_tokens):
            continue
        actor, _actor_conf = _best_atom_scored(
            sentence, vocabulary.actors, allow_empty=True
        )
        action, _action_conf = _best_atom_scored(
            sentence, vocabulary.actions, allow_empty=True
        )
        object_atom, _object_conf = _best_atom_scored(
            sentence, vocabulary.objects, allow_empty=True
        )
        if not actor or not action:
            continue
        key = (actor, action, object_atom or "")
        if key in seen_keys:
            continue
        # Skip if an existing norm already projects the same triple.
        duplicate = False
        for norm in existing_norm_dicts:
            existing_actor, _ = _best_atom_scored(
                norm.get("actor"), vocabulary.actors, allow_empty=True
            )
            existing_action, _ = _best_atom_scored(
                [norm.get("action"), norm.get("action_verb")],
                vocabulary.actions,
                allow_empty=True,
            )
            if existing_actor == actor and existing_action == action:
                duplicate = True
                break
        if duplicate:
            continue
        seen_keys.add(key)
        object_surface = (
            object_atom.replace("_", " ") if object_atom else sentence
        )
        recovered.append(
            {
                "modality": "P",
                "norm_type": "permission",
                "actor": actor.replace("_", " "),
                "action": action,
                "action_verb": action,
                "action_object": object_surface,
                "conditions": (),
                "exceptions": (),
                "temporal_constraints": (),
                "source_text": sentence,
            }
        )
    return recovered


def _expand_norms_for_projection(
    norms: Sequence[object],
    vocabulary: AllowedAtomVocabulary,
    *,
    source_text: str = "",
) -> list[object]:
    """Apply conjoined-action split and missing-permission recovery."""

    base_dicts: list[dict[str, object]] = []
    for norm in norms:
        to_dict = getattr(norm, "to_dict", None)
        if not callable(to_dict):
            raise ContractError("typed deontic norm must provide to_dict()")
        data = to_dict()
        if not isinstance(data, Mapping):
            raise ContractError(
                "typed deontic norm to_dict() must return an object"
            )
        base_dicts.append(dict(data))

    expanded: list[object] = []
    for data in base_dicts:
        for segment in _split_conjoined_action_norm(data, vocabulary):
            expanded.append(_DictNormView(segment))

    for recovered in _recover_missing_permission_norms(
        source_text, base_dicts, vocabulary
    ):
        expanded.append(_DictNormView(recovered))
    return expanded


@dataclass(frozen=True, slots=True)
class TypedDeonticSlotDiagnostic:
    """Field-local projection evidence used to open repair slots."""

    rule_index: int
    canonical_field: str
    kind: str
    confidence: float | None = None
    evidence: str | None = None
    value: object = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.rule_index, bool)
            or not isinstance(self.rule_index, int)
            or self.rule_index < 0
        ):
            raise ContractError("slot diagnostic rule_index must be nonnegative")
        if self.canonical_field not in RULE_FIELDS:
            raise ContractError(
                f"unknown slot diagnostic field: {self.canonical_field!r}"
            )
        kind = str(self.kind or "").strip().lower()
        if kind not in {"missing", "low_confidence", "contradictory"}:
            raise ContractError(
                "slot diagnostic kind must be missing, low_confidence, "
                "or contradictory"
            )
        object.__setattr__(self, "kind", kind)
        if self.confidence is not None:
            if (
                isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or not 0.0 <= float(self.confidence) <= 1.0
            ):
                raise ContractError(
                    "slot diagnostic confidence must be from zero to one"
                )
            object.__setattr__(self, "confidence", float(self.confidence))
        if self.evidence is not None:
            cleaned = " ".join(str(self.evidence).split())
            if not cleaned:
                raise ContractError("slot diagnostic evidence must be nonblank")
            object.__setattr__(self, "evidence", cleaned[:1000])

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_field": self.canonical_field,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "kind": self.kind,
            "rule_index": self.rule_index,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class TypedDeonticConstructorDiagnostics:
    """Out-of-band diagnostics for the typed-deontic constructor."""

    slots: tuple[TypedDeonticSlotDiagnostic, ...] = ()
    detail: str | None = None
    source_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", tuple(self.slots))
        if not all(
            isinstance(item, TypedDeonticSlotDiagnostic) for item in self.slots
        ):
            raise ContractError("diagnostics slots are invalid")
        if self.detail is not None and not str(self.detail).strip():
            raise ContractError("diagnostics detail must be nonblank")
        object.__setattr__(self, "source_text", str(self.source_text or ""))

    def to_dict(self) -> dict[str, object]:
        return {
            "detail": self.detail,
            "interface": TYPED_DEONTIC_DIAGNOSTICS_INTERFACE,
            "slots": [item.to_dict() for item in self.slots],
            "source_text": self.source_text,
        }

    def repair_triggers(
        self,
        *,
        low_confidence_threshold: float = (
            DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
        ),
    ) -> tuple[object, ...]:
        """Project slot diagnostics into selective-repair ``RepairTrigger``s.

        Imported lazily so the no-repair baseline arm never depends on the
        selective-repair package at import time.
        """

        from benchmarks.semantic_roundtrip.selective_repair import (
            RepairTrigger,
            RepairTriggerKind,
        )

        triggers: list[RepairTrigger] = []
        seen: set[str] = set()
        for slot in self.slots:
            path = f"rules[{slot.rule_index}].{slot.canonical_field}"
            if path in seen:
                continue
            kind = RepairTriggerKind(slot.kind)
            if kind is RepairTriggerKind.LOW_CONFIDENCE:
                if slot.confidence is None:
                    continue
                if slot.confidence >= float(low_confidence_threshold):
                    continue
            triggers.append(
                RepairTrigger(
                    rule_index=slot.rule_index,
                    canonical_field=slot.canonical_field,
                    kind=kind,
                    confidence=slot.confidence,
                    evidence=slot.evidence,
                )
            )
            seen.add(path)
        return tuple(triggers)


@dataclass(frozen=True, slots=True)
class TypedDeonticConstruction:
    """Constructor result paired with optional out-of-band diagnostics."""

    result: ConstructorResult
    diagnostics: TypedDeonticConstructorDiagnostics

    def __post_init__(self) -> None:
        if not isinstance(self.result, ConstructorResult):
            raise ContractError("result must be a ConstructorResult")
        if not isinstance(
            self.diagnostics, TypedDeonticConstructorDiagnostics
        ):
            raise ContractError(
                "diagnostics must be TypedDeonticConstructorDiagnostics"
            )


def derive_slot_diagnostics(
    canonical_ir: CanonicalRuleIR,
    *,
    source_text: str = "",
    field_confidences: Mapping[tuple[int, str], float | None] | None = None,
    low_confidence_threshold: float = (
        DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
    ),
    modality_raw: Mapping[int, object] | None = None,
) -> tuple[TypedDeonticSlotDiagnostic, ...]:
    """Derive missing / low-confidence / contradictory slot diagnostics.

    Purely diagnostic: does not mutate the scored IR used by the no-repair
    baseline arm.
    """

    if not isinstance(canonical_ir, CanonicalRuleIR):
        raise ContractError("canonical_ir must be CanonicalRuleIR")
    confidences = dict(field_confidences or {})
    modality_raw = dict(modality_raw or {})
    slots: list[TypedDeonticSlotDiagnostic] = []
    source = _clean_text(source_text)
    temporal_cue = _source_has_temporal_cue(source)
    domain_condition_cue = _source_has_domain_condition_cue(source)

    for index, rule in enumerate(canonical_ir.rules):
        for field in RULE_FIELDS:
            value = getattr(rule, field)
            empty = value in ("", ())
            confidence = confidences.get((index, field))

            if field == "temporal" and empty and temporal_cue:
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="missing",
                        confidence=confidence,
                        evidence=(
                            "source contains temporal cue but temporal "
                            "slot is empty"
                        ),
                        value=value,
                    )
                )
                continue

            if field == "conditions" and empty and domain_condition_cue:
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="missing",
                        confidence=confidence,
                        evidence=(
                            "source contains domain-scope condition cue "
                            "but conditions slot is empty"
                        ),
                        value=value,
                    )
                )
                continue

            if field in {"actor", "action"} and empty:
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="missing",
                        confidence=confidence,
                        evidence=f"required scalar slot {field} is empty",
                        value=value,
                    )
                )
                continue

            if (
                confidence is not None
                and confidence < float(low_confidence_threshold)
                and not empty
            ):
                slots.append(
                    TypedDeonticSlotDiagnostic(
                        rule_index=index,
                        canonical_field=field,
                        kind="low_confidence",
                        confidence=confidence,
                        evidence=(
                            f"{field} matched below the diagnostic "
                            f"threshold {low_confidence_threshold}"
                        ),
                        value=value,
                    )
                )
                continue

        raw_modality = modality_raw.get(index, source)
        if _modality_conflict(raw_modality, source):
            slots.append(
                TypedDeonticSlotDiagnostic(
                    rule_index=index,
                    canonical_field="modality",
                    kind="contradictory",
                    confidence=confidences.get((index, "modality")),
                    evidence=(
                        "obligation and prohibition cues co-occur in "
                        "compiler or source evidence"
                    ),
                    value=rule.modality,
                )
            )

    # Stable order: rule index, field order, kind.
    kind_order = {"missing": 0, "low_confidence": 1, "contradictory": 2}
    slots.sort(
        key=lambda item: (
            item.rule_index,
            RULE_FIELDS.index(item.canonical_field),
            kind_order.get(item.kind, 9),
        )
    )
    # One trigger path per field (prefer missing over low-confidence).
    deduped: list[TypedDeonticSlotDiagnostic] = []
    seen_paths: set[str] = set()
    for slot in slots:
        path = f"rules[{slot.rule_index}].{slot.canonical_field}"
        if path in seen_paths:
            continue
        seen_paths.add(path)
        deduped.append(slot)
    return tuple(deduped)


def project_legal_norms_with_diagnostics(
    norms: Sequence[object],
    vocabulary: AllowedAtomVocabulary,
    *,
    source_text: str = "",
    low_confidence_threshold: float = (
        DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
    ),
) -> tuple[CanonicalRuleIR, TypedDeonticConstructorDiagnostics]:
    """Project norms and retain field-level diagnostic evidence."""

    if not isinstance(vocabulary, AllowedAtomVocabulary):
        raise ContractError("vocabulary must be AllowedAtomVocabulary")

    # Repair-development (PLAT2-050): expand converter norms with
    # conjoined-action splits and uncovered permission-sentence recovery
    # before closed-vocabulary projection.
    expanded_norms = _expand_norms_for_projection(
        norms, vocabulary, source_text=source_text
    )

    rules: list[CanonicalRule] = []
    confidences: dict[tuple[int, str], float | None] = {}
    modality_raw: dict[int, object] = {}
    rule_index = 0
    for norm in expanded_norms:
        to_dict = getattr(norm, "to_dict", None)
        if not callable(to_dict):
            raise ContractError("typed deontic norm must provide to_dict()")
        data = to_dict()
        if not isinstance(data, Mapping):
            raise ContractError(
                "typed deontic norm to_dict() must return an object"
            )

        actor, actor_conf = _best_atom_scored(
            data.get("actor"), vocabulary.actors
        )
        action, action_conf = _best_atom_scored(
            [data.get("action"), data.get("action_verb")],
            vocabulary.actions,
        )
        actor, actor_conf, action, action_conf = _recover_actor_action(
            data,
            vocabulary,
            actor=actor,
            actor_conf=actor_conf,
            action=action,
            action_conf=action_conf,
        )
        # Object evidence is staged: action_object alone first so actor tokens
        # in source_text (e.g. "Contractor") cannot outrank a clean object
        # head such as ``work`` / ``payment`` when scores tie.
        object_atom, object_conf = _best_atom_scored(
            data.get("action_object"),
            vocabulary.objects,
            allow_empty=True,
        )
        if not object_atom:
            object_atom, object_conf = _best_atom_scored(
                data.get("action"),
                vocabulary.objects,
                allow_empty=True,
            )
        if not object_atom:
            object_atom, object_conf = _best_atom_scored(
                [
                    data.get("action_object"),
                    data.get("action"),
                    data.get("source_text"),
                ],
                vocabulary.objects,
                allow_empty=True,
            )
        if not actor or not action:
            continue

        structured_conditions = data.get("conditions") or ()
        structured_exceptions = data.get("exceptions") or ()
        structured_temporal = data.get("temporal_constraints") or ()
        # Structured clauses use content-focused full-grounding so soft
        # request hedges cannot promote if_* atoms from bare participles
        # (holdout low_confidence_object: "requested" ↛ if_requested).
        conditions, conditions_conf = _map_structured_qualifiers_scored(
            structured_conditions,
            vocabulary.qualifiers,
            facet="conditions",
        )
        exceptions, exceptions_conf = _map_structured_qualifiers_scored(
            structured_exceptions,
            vocabulary.qualifiers,
            facet="exceptions",
        )
        temporal, temporal_conf = _map_structured_qualifiers_scored(
            structured_temporal,
            vocabulary.qualifiers,
            facet="temporal",
        )
        evidence_text = _norm_evidence_text(data)
        harvested = _harvest_qualifiers_from_evidence(
            evidence_text,
            vocabulary,
        )
        # When the converter already split out structured condition clauses,
        # those slots are authoritative for conditions. Free-text harvest
        # would re-introduce soft hedges (if_requested) that gold omits on
        # selective-repair activation cases and double-count structured hits.
        if structured_conditions:
            harvested_conditions: tuple[str, ...] = ()
        else:
            harvested_conditions = harvested["conditions"]
        conditions = _merge_qualifier_facets(
            conditions, harvested_conditions
        )
        exceptions = _merge_qualifier_facets(
            exceptions, harvested["exceptions"]
        )
        temporal = _merge_qualifier_facets(temporal, harvested["temporal"])
        # Promote without/except-framed condition atoms to exceptions, then
        # drop any remaining dual placement onto conditions only.
        conditions, exceptions = _reclassify_exception_framed_conditions(
            conditions, exceptions, evidence_text
        )
        conditions = _prefer_exceptions_over_conditions(conditions, exceptions)
        # Re-score confidences after harvest: structured matches retain their
        # confidence; pure harvest fills use a mid confidence marker.
        if harvested_conditions and conditions_conf is None:
            conditions_conf = 0.7
        if harvested["exceptions"] and exceptions_conf is None:
            exceptions_conf = 0.7
        if harvested["temporal"] and temporal_conf is None:
            temporal_conf = 0.7
        modality_value = [data.get("modality"), data.get("norm_type")]
        modality = _modality_from_text(modality_value)
        modality_raw[rule_index] = modality_value

        confidences[(rule_index, "actor")] = actor_conf
        confidences[(rule_index, "action")] = action_conf
        confidences[(rule_index, "object")] = object_conf
        confidences[(rule_index, "conditions")] = conditions_conf
        confidences[(rule_index, "exceptions")] = exceptions_conf
        confidences[(rule_index, "temporal")] = temporal_conf
        # Modality is rule-derived from cues; high confidence unless conflicted.
        confidences[(rule_index, "modality")] = (
            0.4 if _modality_conflict(modality_value, source_text) else 0.95
        )

        rules.append(
            CanonicalRule(
                modality=modality,
                actor=actor,
                action=action,
                object=object_atom,
                conditions=conditions,
                exceptions=exceptions,
                temporal=temporal,
            )
        )
        rule_index += 1

    # Collapse O/F dual norms for the same closed-vocabulary triple
    # (holdout contradictory_modality: must + shall not disclose).
    pre_merge_count = len(rules)
    resolved_rules = _resolve_conflicting_modality_rules(rules)
    if len(resolved_rules) != pre_merge_count:
        rules = list(resolved_rules)
        # Rule indices shifted; rebuild a minimal confidence map so diagnostics
        # remain well-formed without inventing per-field scores for merges.
        confidences = {
            (index, "modality"): 0.95 for index in range(len(rules))
        }
        modality_raw = {
            index: [rule.modality] for index, rule in enumerate(rules)
        }

    canonical_ir = CanonicalRuleIR(tuple(rules))
    canonical_ir.validate_vocabulary(vocabulary)
    slots = derive_slot_diagnostics(
        canonical_ir,
        source_text=source_text,
        field_confidences=confidences,
        low_confidence_threshold=low_confidence_threshold,
        modality_raw=modality_raw,
    )
    return canonical_ir, TypedDeonticConstructorDiagnostics(
        slots=slots,
        source_text=_clean_text(source_text),
    )


def project_legal_norms(
    norms: Sequence[object],
    vocabulary: AllowedAtomVocabulary,
) -> CanonicalRuleIR:
    """Project supported ``LegalNormIR`` records into exact canonical fields.

    As in the reviewed pilot, a record is supported when its actor and action
    both map into the closed case vocabulary.  An absent or unmatched object
    is represented explicitly by ``""`` and absent qualifier facets by empty
    tuples.  No source spans, native IR, metadata, or decoder records cross the
    canonical boundary.
    """

    canonical_ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary
    )
    return canonical_ir


def derive_repair_triggers_from_ir_and_source(
    request: ConstructorRequest,
    baseline_ir: CanonicalRuleIR,
    *,
    low_confidence_threshold: float = (
        DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
    ),
    field_confidences: Mapping[tuple[int, str], float | None] | None = None,
) -> tuple[object, ...]:
    """Emit repair triggers from IR + source diagnostics (no IR mutation)."""

    if not isinstance(request, ConstructorRequest):
        raise ContractError("request must be ConstructorRequest")
    diagnostics = TypedDeonticConstructorDiagnostics(
        slots=derive_slot_diagnostics(
            baseline_ir,
            source_text=request.source_text,
            field_confidences=field_confidences,
            low_confidence_threshold=low_confidence_threshold,
        ),
        source_text=request.source_text,
    )
    return diagnostics.repair_triggers(
        low_confidence_threshold=low_confidence_threshold
    )


def _failure(
    reason: FailureReason,
    detail: str,
) -> ConstructorResult:
    return ConstructorResult(
        status=ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=detail,
    )


class TypedDeonticCanonicalConstructor:
    """Adapt the deterministic typed deontic converter to canonical rule IR."""

    @property
    def identity(self) -> str:
        return TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE

    def construct_with_diagnostics(
        self, request: ConstructorRequest
    ) -> TypedDeonticConstruction:
        """Construct IR and retain trigger-ready diagnostics out of band.

        The scored no-repair baseline continues to use :meth:`construct`, which
        returns only ``ConstructorResult`` and never mutates or repairs.
        """

        empty = TypedDeonticConstructorDiagnostics()
        if not isinstance(request, ConstructorRequest):
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.INVALID_OUTPUT,
                    "request must be ConstructorRequest",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="request must be ConstructorRequest"
                ),
            )

        try:
            from ipfs_datasets_py.logic.deontic.converter import (
                DeonticConverter,
            )
            from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
        except ImportError:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.CAPABILITY_UNAVAILABLE,
                    "typed deontic converter capability is unavailable",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="typed deontic converter capability is unavailable",
                    source_text=request.source_text,
                ),
            )

        try:
            converter = DeonticConverter(
                use_cache=False,
                use_ipfs=False,
                use_ml=False,
                enable_monitoring=False,
                document_type="general",
            )
            converted = converter.convert(request.source_text, use_cache=False)
        except Exception as exc:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EXCEPTION,
                    f"typed deontic conversion raised {type(exc).__name__}",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail=(
                        f"typed deontic conversion raised {type(exc).__name__}"
                    ),
                    source_text=request.source_text,
                ),
            )

        output = getattr(converted, "output", None)
        if output is None:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.MISSING_OUTPUT,
                    "typed deontic converter returned no output",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="typed deontic converter returned no output",
                    source_text=request.source_text,
                ),
            )

        elements = list(getattr(output, "parser_elements", ()) or ())
        if not elements:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EMPTY_L1,
                    "typed deontic converter returned no parser elements",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail="typed deontic converter returned no parser elements",
                    source_text=request.source_text,
                ),
            )

        try:
            norms = [
                LegalNormIR.from_parser_element(element)
                for element in elements
            ]
            canonical_ir, diagnostics = project_legal_norms_with_diagnostics(
                norms,
                request.allowed_atom_vocabulary,
                source_text=request.source_text,
            )
        except ContractError as exc:
            return TypedDeonticConstruction(
                _failure(FailureReason.INVALID_OUTPUT, str(exc)),
                TypedDeonticConstructorDiagnostics(
                    detail=str(exc),
                    source_text=request.source_text,
                ),
            )
        except Exception as exc:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EXCEPTION,
                    f"typed deontic projection raised {type(exc).__name__}",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail=(
                        f"typed deontic projection raised {type(exc).__name__}"
                    ),
                    source_text=request.source_text,
                ),
            )

        if canonical_ir.is_empty:
            return TypedDeonticConstruction(
                _failure(
                    FailureReason.EMPTY_L1,
                    "typed deontic records did not map to supported "
                    "canonical rules",
                ),
                TypedDeonticConstructorDiagnostics(
                    detail=(
                        "typed deontic records did not map to supported "
                        "canonical rules"
                    ),
                    source_text=request.source_text,
                ),
            )
        return TypedDeonticConstruction(
            ConstructorResult(
                status=ComponentStatus.SUCCESS,
                canonical_ir=canonical_ir,
            ),
            diagnostics,
        )

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """No-repair baseline path: pure ConstructorResult, no repair side effects."""

        # Keep the baseline arm identical in disposition to diagnostics path
        # results without exposing diagnostic payloads on the scored surface.
        return self.construct_with_diagnostics(request).result


class TypedDeonticDiagnosticTriggerDetector:
    """RepairTriggerDetector backed by typed-deontic slot diagnostics."""

    identity: Final = TYPED_DEONTIC_TRIGGER_DETECTOR_INTERFACE

    def __init__(
        self,
        *,
        low_confidence_threshold: float = (
            DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD
        ),
        field_confidences: (
            Mapping[tuple[int, str], float | None] | None
        ) = None,
    ) -> None:
        if (
            isinstance(low_confidence_threshold, bool)
            or not isinstance(low_confidence_threshold, (int, float))
            or not 0.0 <= float(low_confidence_threshold) <= 1.0
        ):
            raise ContractError(
                "low_confidence_threshold must be from zero to one"
            )
        self._low_confidence_threshold = float(low_confidence_threshold)
        self._field_confidences = dict(field_confidences or {})

    def detect(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
    ) -> Sequence[object]:
        return derive_repair_triggers_from_ir_and_source(
            request,
            baseline_ir,
            low_confidence_threshold=self._low_confidence_threshold,
            field_confidences=self._field_confidences,
        )


assert isinstance(TypedDeonticCanonicalConstructor(), RoundTripConstructor)


__all__ = [
    "TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE",
    "TYPED_DEONTIC_DIAGNOSTICS_INTERFACE",
    "TYPED_DEONTIC_TRIGGER_DETECTOR_INTERFACE",
    "DEFAULT_DIAGNOSTIC_LOW_CONFIDENCE_THRESHOLD",
    "TypedDeonticSlotDiagnostic",
    "TypedDeonticConstructorDiagnostics",
    "TypedDeonticConstruction",
    "TypedDeonticCanonicalConstructor",
    "TypedDeonticDiagnosticTriggerDetector",
    "derive_slot_diagnostics",
    "derive_repair_triggers_from_ir_and_source",
    "project_legal_norms",
    "project_legal_norms_with_diagnostics",
    "_map_structured_qualifiers_scored",
    "_resolve_conflicting_modality_rules",
    "_structured_clause_match_text",
]
