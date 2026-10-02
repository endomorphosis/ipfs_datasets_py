"""Declare bounded instruction grammar coverage before optional learned advice.

This is a lexical scope gate, not a semantic parser or a correctness checker.
It consumes a whole instruction and exports no semantic slots or model targets.
Unsupported text remains the planner's original input. Accepted text can still
be misunderstood by a model; recognition of this grammar conveys no authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

SCHEMA = "intent-instruction-scope/v1"
POLICY_ID = "intent-single-action-lowercase-grammar/v2"
MAX_CHARACTERS = 4096
MAX_WORDS = 48
MAX_ACTOR_WORDS = 4
MAX_OBJECT_WORDS = 12
MAX_SLOT_CHARACTERS = 160

POLICY_SCOPE_LIMITS = (
    "coverage_of_a_declared_lexical_grammar_not_complete_natural_language_recognition",
    "scope_acceptance_does_not_validate_source_meaning_or_model_predictions",
    "single_action_only_no_conditions_workflow_quantifiers_or_reference_resolution",
    "opaque_lowercase_object_phrases_have_no_verified_internal_semantics",
    "unrecognized_bare_verbs_and_ambiguous_constructions_may_conservatively_abstain",
    "case_sensitive_identifiers_code_and_multiline_instructions_are_out_of_scope",
    "no_semantic_slots_or_expected_targets_are_supplied_to_learned_inference",
    "unsupported_advice_never_removes_or_rewrites_the_original_planner_instruction",
)

# A declared command vocabulary for bare imperatives, not a classifier trained
# on evaluation examples. Explicit modal positions can contain opaque verbs.
_BARE_ACTIONS = frozenset((
    "add adjust aggregate align analyze annotate append archive assemble audit backup benchmark "
    "build cache calculate check clean clear clone collect compare compile compress compute configure "
    "confirm connect consolidate convert copy count create debug decode decrypt delete deploy describe "
    "design detect diagnose diff disable disconnect document download edit enable encode encrypt "
    "enumerate evaluate examine execute expand export extract fetch filter find fix format generate "
    "group implement import improve index initialize inspect install integrate inventory isolate "
    "lint list load locate log measure merge migrate minimize monitor move normalize open optimize "
    "package parse patch pin prepare preserve print profile publish read rebuild record recover "
    "refactor refresh register remove rename render repair replace report reproduce rerun reset "
    "resolve restore retrieve review reuse revise rotate run save scan search select serialize "
    "show simplify sort split start stop store summarize synchronize test trace train transform "
    "translate trim uninstall update upgrade upload use validate verify view write"
).split())
_ACTOR_MODALS = (
    "is required to", "is forbidden to", "is prohibited from", "is allowed to",
    "is permitted to", "is advised to", "is recommended to", "intends to",
    "must not", "shall not", "must", "shall", "may", "should",
)
_OMITTED_MODALS = ("must not", "shall not", "do not", "never", "must", "shall", "may", "should")
_HEADINGS = ("must not do", "must do", "required", "prohibited", "permitted", "recommended", "intended")
_CONDITIONAL = frozenset((
    "if when unless until before after while once whenever wherever assuming provided given because "
    "whether whereas since notwithstanding except without"
).split())
_WORKFLOW = frozenset((
    "then otherwise meanwhile subsequently finally first secondly thirdly next afterwards"
).split())
_CONNECTIVES = frozenset(("and", "or", "nor", "but", "versus", "alternatively"))
_REFERENCES = frozenset((
    "i me my mine myself you your yours yourself yourselves we us our ours ourselves "
    "he him his himself she her hers herself it its itself they them their theirs themselves "
    "this that these those former latter above below previous same such here there whose"
).split())
_QUANTIFIERS = frozenset((
    "all any every each either neither both none no only always eventually exactly least most"
).split())
_QUESTION_LEADS = frozenset(("can", "could", "would", "will", "who", "what", "why", "how", "where",
                             "whether", "is", "are", "was", "were", "does", "did"))
_MODAL_WORDS = frozenset((
    "must shall may should intends required forbidden prohibited allowed permitted advised recommended "
    "not never ought can could would will"
).split())
_SUBORDINATE = frozenset(("to", "than", "as", "which", "who", "whom", "is", "are", "was", "were",
                          "be", "been", "being", "has", "have", "had", "does", "did"))
_ROLE_CUES = frozenset(("agent", "developer", "operator", "system", "user", "service", "administrator"))
_FUNCTION_WORDS = frozenset(("a", "an", "the", "please", "ask", "do", "for", "from", "of", "in",
                             "on", "by", "with", "at", "into", "through", "via", "about"))
_META_HEADS = frozenset((
    "statement statements clause clauses condition conditions expression expressions operator operators "
    "keyword keywords token tokens branch branches loop loops block blocks guard guards"
).split())
_META_MARKERS = _CONDITIONAL | _WORKFLOW | _CONNECTIVES | _MODAL_WORDS
_RESERVED_ROLE_WORDS = (_CONDITIONAL | _WORKFLOW | _CONNECTIVES | _REFERENCES | _QUANTIFIERS |
                        _QUESTION_LEADS | _MODAL_WORDS | _SUBORDINATE | _FUNCTION_WORDS)
_INITIAL_CUES = (_BARE_ACTIONS | _CONDITIONAL | _WORKFLOW | _QUESTION_LEADS |
                 frozenset(("please", "required", "prohibited", "permitted", "recommended", "intended",
                            "must", "shall", "may", "should", "do", "never", "the")))
_AUTHORITY = {"proof_authority": False, "execution_authority": False, "completion_authority": False,
              "omission_authority": False, "semantic_correctness_authority": False}

_ATOM = r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*"
_PHRASE = _ATOM + r"(?: " + _ATOM + r")*"
_ACTION_OBJECT = re.compile(r"(?P<action>" + _ATOM + r") (?P<object>" + _PHRASE + r")\Z")
_ACTOR = r"(?:the )?(?P<actor>" + _ATOM + r"(?: " + _ATOM + r"){0,3})"
_ACTOR_CLAUSE = re.compile(_ACTOR + r" (?P<modal>" + "|".join(map(re.escape, _ACTOR_MODALS)) +
                           r") (?P<body>" + _PHRASE + r")\Z")
_DELEGATED = re.compile(r"please ask " + _ACTOR + r" to (?P<body>" + _PHRASE + r")\Z")
_HEADING = re.compile(r"(?P<heading>" + "|".join(map(re.escape, _HEADINGS)) + r"): (?P<body>" + _PHRASE + r")\Z")


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def instruction_scope_policy():
    """Return a fresh serializable declaration; modifying it changes no policy."""
    return {
        "schema": "intent-instruction-scope-policy/v1", "policy_id": POLICY_ID,
        "limits": {"characters": MAX_CHARACTERS, "words": MAX_WORDS, "actor_words": MAX_ACTOR_WORDS,
                   "object_words": MAX_OBJECT_WORDS, "slot_characters": MAX_SLOT_CHARACTERS},
        "lexical_atom_pattern": _ATOM,
        "productions": {
            "actor_modal": "[the] ACTOR MODAL ACTION OBJECT [.]",
            "delegated_request": "please ask [the] ACTOR to ACTION OBJECT [.]",
            "bare_imperative": "[please] KNOWN_ACTION OBJECT [.]",
            "omitted_actor_modal": "MODAL ACTION OBJECT [.]",
            "negative_request": "please (do not|never) ACTION OBJECT [.]",
            "modal_heading": "HEADING: [please] ACTION OBJECT [.]",
            "metalinguistic_object": "[the|a|an] MARKER META_HEAD",
        },
        "bare_actions": sorted(_BARE_ACTIONS), "actor_modals": list(_ACTOR_MODALS),
        "omitted_actor_modals": list(_OMITTED_MODALS), "modal_headings": list(_HEADINGS),
        "conditional_markers": sorted(_CONDITIONAL), "workflow_markers": sorted(_WORKFLOW),
        "connectives": sorted(_CONNECTIVES), "reference_words": sorted(_REFERENCES),
        "quantifier_words": sorted(_QUANTIFIERS), "question_leads": sorted(_QUESTION_LEADS),
        "modal_words": sorted(_MODAL_WORDS), "subordinate_words": sorted(_SUBORDINATE),
        "role_cues": sorted(_ROLE_CUES), "function_words": sorted(_FUNCTION_WORDS),
        "meta_heads": sorted(_META_HEADS), "meta_markers": sorted(_META_MARKERS),
        "capitalization": "only recognized initial command/grammar cues; actor names remain lowercase",
        "normalization": "outer whitespace and horizontal whitespace; original source remains bound",
        "object_semantics": "opaque phrase, no semantic or code-reference resolution",
        "scope_limits": list(POLICY_SCOPE_LIMITS), "source_semantics_verified": False,
        **_AUTHORITY,
    }


def _meta_object(tokens):
    if tokens and tokens[0] in {"the", "a", "an"}:
        tokens = tokens[1:]
    return len(tokens) == 2 and tokens[0] in _META_MARKERS and tokens[1] in _META_HEADS


def _body_reason(body, *, opaque_action):
    match = _ACTION_OBJECT.fullmatch(body)
    if match is None:
        return "incomplete_or_unrecognized_action_object_grammar"
    action, object_ = match["action"], match["object"]
    if len(action) > MAX_SLOT_CHARACTERS:
        return "action_atom_exceeds_codec_bound"
    if action in _RESERVED_ROLE_WORDS or action in _ROLE_CUES:
        return "action_position_contains_grammar_or_role_word"
    if not opaque_action and action not in _BARE_ACTIONS:
        return "bare_action_unclassified_by_policy"
    tokens = object_.split()
    if len(tokens) > MAX_OBJECT_WORDS or len(object_) > MAX_SLOT_CHARACTERS:
        return "object_phrase_exceeds_codec_bound"
    if _meta_object(tokens):
        return None
    words = set(tokens)
    if words & _CONDITIONAL:
        return "object_contains_conditional_temporal_or_exception_scope"
    if words & _WORKFLOW:
        return "object_contains_workflow_or_order_scope"
    if words & _CONNECTIVES:
        return "object_contains_coordination_or_disjunction"
    if words & _REFERENCES:
        return "object_requires_reference_resolution"
    if words & _QUANTIFIERS:
        return "object_contains_quantified_or_global_scope"
    if words & _MODAL_WORDS:
        return "object_contains_nested_modal_or_negative_scope"
    if words & _SUBORDINATE:
        return "object_contains_subordinate_or_predicative_scope"
    return None


def _actor_reason(actor):
    if len(actor) > MAX_SLOT_CHARACTERS or len(actor.split()) > MAX_ACTOR_WORDS:
        return "actor_phrase_exceeds_codec_bound"
    if set(actor.split()) & _REFERENCES:
        return "actor_requires_reference_resolution"
    if set(actor.split()) & _RESERVED_ROLE_WORDS:
        return "actor_contains_unsupported_grammar_words"
    return None


def _recognize(text, *, capitalized_initial):
    """Recognize a whole positive production; do not construct semantic slots."""
    first = text.split(" ", 1)[0].removesuffix(":")
    if first in _CONDITIONAL:
        return None, "leading_conditional_or_temporal_scope"
    if first in _WORKFLOW:
        return None, "leading_workflow_or_reference_scope"
    if first in _QUESTION_LEADS:
        return None, "question_or_nonimperative_leading_grammar"

    delegated = _DELEGATED.fullmatch(text)
    if delegated:
        reason = _actor_reason(delegated["actor"]) or _body_reason(delegated["body"], opaque_action=True)
        return "delegated_single_action_request", reason
    heading = _HEADING.fullmatch(text)
    if heading:
        body = heading["body"]
        if body.startswith("please "):
            body = body[7:]
        return "modal_heading", _body_reason(body, opaque_action=True)
    actor = _ACTOR_CLAUSE.fullmatch(text)
    if actor:
        if capitalized_initial and not text.startswith("the "):
            return "actor_modal", "case_sensitive_or_capitalized_actor"
        return "actor_modal", _actor_reason(actor["actor"]) or _body_reason(actor["body"], opaque_action=True)
    for modal in _OMITTED_MODALS:
        if text.startswith(modal + " "):
            return "omitted_actor_modal", _body_reason(text[len(modal) + 1:], opaque_action=True)
    for negative in ("please do not ", "please never "):
        if text.startswith(negative):
            return "negative_request", _body_reason(text[len(negative):], opaque_action=True)
    if text.startswith("please "):
        return "please_imperative", _body_reason(text[7:], opaque_action=False)
    if ":" in text:
        return None, "unrecognized_or_nested_heading_grammar"
    return "bare_imperative", _body_reason(text, opaque_action=False)


def assess_intent_instruction_scope(instruction):
    """Assess declared coverage without loading a model or exporting frame slots.

    Every string receives a source-bound report, including unsupported Unicode
    and oversize strings. Non-string calls are API errors. Surrogate-pass hashing
    binds rejected non-scalar strings without normalizing their original value.
    """
    if type(instruction) is not str:
        raise ValueError("exact original instruction string required")
    source = instruction.encode("utf-8", errors="surrogatepass")
    policy = instruction_scope_policy()
    report = {
        "schema": SCHEMA, "policy_id": POLICY_ID, "policy_sha256": _sha(_wire(policy)),
        "producer_sha256": _sha(Path(__file__).read_bytes()),
        "instruction_sha256": _sha(source), "instruction_bytes": len(source),
        "instruction_chars": len(instruction), "instruction_word_count": len(instruction.split()),
        "status": "unsupported_by_scope_policy", "eligible_for_inference": False,
        "grammar_shape": None, "complete_consumption": False, "normalization": [], "reasons": [],
        "scope_limits": list(POLICY_SCOPE_LIMITS), "continue_planning": True,
        "raw_instruction_preserved": True, "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "source_semantics_verified": False, **_AUTHORITY,
    }
    reason = None
    text = instruction.strip()
    if not text:
        reason = "empty_instruction"
    elif len(instruction) > MAX_CHARACTERS:
        reason = "instruction_character_limit"
    elif report["instruction_word_count"] > MAX_WORDS:
        reason = "instruction_word_limit"
    elif not instruction.isascii():
        reason = "non_ascii_or_invalid_unicode_outside_declared_grammar"
    elif any(char in text for char in "\r\n"):
        reason = "multiline_instruction_outside_declared_grammar"
    elif "?" in text:
        reason = "question_punctuation_outside_declared_grammar"
    elif "<" in text or ">" in text:
        reason = "reserved_model_or_ir_markup"
    elif any(ord(char) < 32 and char != "\t" for char in text) or "\x7f" in text:
        reason = "control_character_outside_declared_grammar"
    else:
        if text != instruction:
            report["normalization"].append("strip_outer_whitespace")
        collapsed = re.sub(r"[ \t]+", " ", text)
        if collapsed != text:
            report["normalization"].append("collapse_horizontal_whitespace")
        text = collapsed
        capitalized = False
        match = re.match(r"[A-Za-z][A-Za-z0-9_-]*", text)
        if match and match[0] != match[0].lower():
            token = match[0]
            if token[0].isupper() and token[1:] == token[1:].lower() and token.lower() in _INITIAL_CUES:
                text = token.lower() + text[len(token):]
                capitalized = True
                report["normalization"].append("lowercase_recognized_initial_grammar_token")
        if any(character.isupper() for character in text):
            reason = "case_sensitive_or_capitalized_lexical_content"
        else:
            # One optional terminal period; every remaining punctuation mark
            # must belong to a modal heading or to an internal lexical atom.
            text = text.removesuffix(".")
            if not text or re.search(r"[^a-z0-9_ :\-]", text):
                reason = "punctuation_code_or_multiple_clauses_outside_declared_grammar"
            else:
                shape, reason = _recognize(text, capitalized_initial=capitalized)
                report["grammar_shape"] = shape
    if reason is None:
        report["status"] = "within_declared_single_action_grammar"
        report["eligible_for_inference"] = True
        report["complete_consumption"] = True
    else:
        report["reasons"] = [reason]
    report["report_sha256"] = _sha(_wire(report))
    return report


def validate_instruction_scope_report(report, *, instruction):
    """Reject altered policy, source, reason, coverage or authority by replay."""
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("instruction scope report required")
    expected = assess_intent_instruction_scope(instruction)
    try:
        equal = _wire(report) == _wire(expected)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("instruction scope report must contain canonical JSON values") from exc
    if not equal:
        raise ValueError("instruction scope report differs from source/policy replay")
    return report
