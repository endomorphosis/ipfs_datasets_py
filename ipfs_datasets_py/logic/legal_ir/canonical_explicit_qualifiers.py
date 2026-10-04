"""Opt-in, complete single-rule parsing with explicit qualifier connectives.

This controlled English profile is independent of the frozen typed-deontic
compiler. It matches caller-declared atom surfaces exactly, consumes the whole
sentence, and never calls a converter, model, or fallback. Named qualifiers
remain opaque atoms: parsing is not native interpretation or source fidelity.
"""
from __future__ import annotations

import re

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    CanonicalContractError,
    CanonicalDiagnostic,
    CanonicalError,
    CanonicalErrorCode,
    CanonicalRoundTripIR,
    CanonicalRule,
    CompilerRequest,
    CompilerResult,
    ComponentTrace,
    DiagnosticSeverity,
    OperationStatus,
    SourceMapEntry,
    UnsupportedDisposition,
    UnsupportedSemantic,
)
from ipfs_datasets_py.logic.legal_ir.canonical_source_guards import analyze_canonical_source
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

PROFILE = "explicit-qualifier-single-rule/v1"
MAX_SOURCE_CHARS = 16_384
MAX_VOCABULARY_ATOMS = 256
MAX_PARSE_ATTEMPTS = 4096
_ATOM = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*\Z")
_RESERVED = frozenset({"and", "or", "if", "unless", "must", "shall", "may", "not", "no", "never", "absent",
                       "he", "she", "they", "it", "we", "you", "i", "that", "who", "every", "each", "exactly"})
_TIMES = frozenset({"within", "before", "after", "during", "until"})
_MODALS = (("must not", "F"), ("shall not", "F"), ("must", "O"), ("shall", "O"), ("may", "P"))


def explicit_qualifier_configuration():
    return {"profile": PROFILE, "interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
            "grammar": "one_named_actor_modal_action_object_temporal_if_unless",
            "leading_condition": "if_clause_comma", "conditions_connective": "and",
            "exceptions_connective": "or", "temporal_connective": "and",
            "atom_match": "exact_declared_surface_with_explicit_article_copula_and_applies_forms",
            "articles": ["the", "a", "an"], "condition_copulas": ["is", "are", "has been", "have been"],
            "condition_copula_position": "before_last_atom_word", "exception_suffix": "applies",
            "atom_spelling": "lowercase_ascii_alphanumeric_underscore",
            "reserved_atom_words": sorted(_RESERVED),
            "case_and_whitespace": "ascii_case_insensitive_whitespace_collapse",
            "modal_surfaces": dict(_MODALS), "source_guard": "source-only-attributed-pronoun-pattern/v1",
            "max_source_chars": MAX_SOURCE_CHARS, "max_vocabulary_atoms_per_slot": MAX_VOCABULARY_ATOMS,
            "max_parse_attempts": MAX_PARSE_ATTEMPTS, "partial_projection": False,
            "fallback_allowed": False, "model_calls": 0, "native_proof": False,
            "benchmark_admitted": False, "default_compiler_replaced": False}


EXPLICIT_QUALIFIER_CONFIG_CID = cid_for_dag_json(explicit_qualifier_configuration())


class _ParseError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _surfaces(atom, facet):
    bare = atom.replace("_", " ")
    forms = {bare}
    words = bare.split()
    if facet == "conditions" and len(words) >= 2:
        subject, predicate = " ".join(words[:-1]), words[-1]
        forms.update(f"{subject} {copula} {predicate}" for copula in ("is", "are", "has been", "have been"))
    if facet == "exceptions":
        forms.add(bare + " applies")
    if facet in {"actor", "object", "conditions", "exceptions"}:
        forms.update(article + " " + surface for surface in tuple(forms) for article in ("the", "a", "an"))
    return forms


def _tables(vocabulary):
    tables = {}
    for facet, atoms in (("actor", vocabulary.actors), ("action", vocabulary.actions), ("object", vocabulary.objects),
                         ("conditions", vocabulary.qualifiers), ("exceptions", vocabulary.qualifiers), ("temporal", vocabulary.qualifiers)):
        if len(atoms) > MAX_VOCABULARY_ATOMS:
            raise _ParseError("explicit_qualifier.vocabulary_bound", "Caller vocabulary exceeds the declared slot bound.")
        table = {}
        for atom in atoms:
            if not _ATOM.fullmatch(atom) or set(atom.split("_")) & _RESERVED:
                raise _ParseError("explicit_qualifier.unsupported_atom_surface", "An atom spelling conflicts with the controlled grammar.")
            if facet == "temporal" and atom.split("_", 1)[0] not in _TIMES:
                continue
            for surface in _surfaces(atom, facet):
                if surface in table and table[surface] != atom:
                    raise _ParseError("explicit_qualifier.ambiguous_atom_surface", "Two caller atoms have the same supported surface.")
                table[surface] = atom
        tables[facet] = table
    return tables


def _consume_prefix(text, table):
    return [(atom, text[len(surface):].strip()) for surface, atom in sorted(table.items())
            if text == surface or text.startswith(surface + " ")]


def _qualifiers(text, facet, table):
    if not text:
        return ()
    connector = "or" if facet == "exceptions" else "and"
    forbidden = "and" if connector == "or" else "or"
    if re.search(rf"\b{forbidden}\b", text):
        raise _ParseError("explicit_qualifier.unsupported_connective", f"The {facet} clause requires '{connector}' exclusively.")
    parts = text.split(" " + connector + " ")
    if any(not part or part not in table for part in parts):
        raise _ParseError("explicit_qualifier.unmapped_" + facet, f"Every {facet} phrase must exactly match a declared atom surface.")
    values = [table[part] for part in parts]
    if len(set(values)) != len(values):
        raise _ParseError("explicit_qualifier.repeated_qualifier", "Repeated qualifier atoms require explicit handling.")
    return tuple(sorted(values))


def _split_clauses(text):
    leading = ""
    if text.startswith("if "):
        if "," not in text:
            raise _ParseError("explicit_qualifier.leading_condition_delimiter", "A leading condition requires its separating comma.")
        leading, text = text[3:].split(",", 1)
        text = text.strip()
    # Commas may only delimit the suffix exception clause; never erase them.
    text = text.replace(", unless ", " unless ")
    if "," in text or "," in leading:
        raise _ParseError("explicit_qualifier.unsupported_punctuation", "Only declared clause-separating commas are supported.")
    markers = list(re.finditer(r"\b(if|unless)\b", text))
    if len(markers) > 2 or [match.group() for match in markers] not in ([], ["if"], ["unless"], ["if", "unless"]):
        raise _ParseError("explicit_qualifier.unsupported_clause_order", "Only one condition and one final exception clause are supported.")
    if leading and any(match.group() == "if" for match in markers):
        raise _ParseError("explicit_qualifier.duplicate_condition_clause", "Leading and suffix conditions cannot both occur.")
    core = text[:markers[0].start()].strip() if markers else text
    conditions, exceptions = leading, ""
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        clause = text[marker.end():end].strip()
        if not clause:
            raise _ParseError("explicit_qualifier.empty_clause", "An explicit qualifier clause cannot be empty.")
        if marker.group() == "if":
            conditions = clause
        else:
            exceptions = clause
    return core, conditions, exceptions


def _parse(source, vocabulary):
    if len(source) > MAX_SOURCE_CHARS or any(ord(character) > 127 for character in source):
        raise _ParseError("explicit_qualifier.source_bound_or_alphabet", "The source must fit the bounded ASCII grammar.")
    body = " ".join(source.lower().split())
    if body.endswith("."):
        body = body[:-1].rstrip()
    if not body or re.search(r"[^a-z0-9 ,]", body):
        raise _ParseError("explicit_qualifier.unsupported_punctuation", "The complete source must be one controlled sentence.")
    tables = _tables(vocabulary)
    core, condition_text, exception_text = _split_clauses(body)
    conditions = _qualifiers(condition_text, "conditions", tables["conditions"])
    exceptions = _qualifiers(exception_text, "exceptions", tables["exceptions"])
    rules, attempts, last_error = {}, 0, None
    for actor, after_actor in _consume_prefix(core, tables["actor"]):
        for surface, modality in _MODALS:
            if not after_actor.startswith(surface + " "):
                continue
            tail = after_actor[len(surface):].strip()
            for action, after_action in _consume_prefix(tail, tables["action"]):
                objects = _consume_prefix(after_action, tables["object"]) + [("", after_action)]
                for object_atom, temporal_text in objects:
                    attempts += 1
                    if attempts > MAX_PARSE_ATTEMPTS:
                        raise _ParseError("explicit_qualifier.parse_bound", "The complete-match search exceeds its bound.")
                    try:
                        temporal = _qualifiers(temporal_text, "temporal", tables["temporal"])
                    except _ParseError as error:
                        last_error = error
                        continue
                    rule = CanonicalRule(modality, actor, action, object_atom, conditions, exceptions, temporal)
                    rules[rule.rule_cid] = rule
    if len(rules) > 1:
        raise _ParseError("explicit_qualifier.ambiguous_complete_parse", "Multiple distinct complete parses require clarification.")
    if not rules:
        if last_error is not None:
            raise last_error
        raise _ParseError("explicit_qualifier.unmapped_core_or_unsupported_syntax", "Named actor, modality, action, object, and complete clause structure must match exactly.")
    return next(iter(rules.values()))


def _provenance(request, terminal_stage):
    body = {"interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE, "profile": PROFILE,
            "request_cid": request.request_cid, "source_cid": request.source_cid, "policy_cid": request.policy_cid,
            "compiler_config_cid": EXPLICIT_QUALIFIER_CONFIG_CID, "terminal_stage": terminal_stage,
            "complete_source_consumption": terminal_stage == "complete", "opt_in": True,
            "benchmark_admitted": False, "default_compiler_replaced": False,
            "deterministic": True, "fallback_allowed": False, "fallback_used": False,
            "model_call_count": 0, "learned_stages": [], "native_semantics_verified": False}
    return {**body, "provenance_cid": cid_for_dag_json(body)}


def _abstain(request, code, message, span=None):
    start, end = span if span is not None else (0, len(request.source_text))
    issue = UnsupportedSemantic(code, message, UnsupportedDisposition.ABSTAIN, request.source_cid, start, end)
    return CompilerResult(OperationStatus.ABSTAINED, request.request_cid, unsupported_semantics=(issue,),
                          provenance=_provenance(request, "source_grammar_validation"),
                          diagnostics=(CanonicalDiagnostic(code, message, DiagnosticSeverity.ERROR,
                                                           source_cid=request.source_cid, start=start, end=end),),
                          error=CanonicalError(CanonicalErrorCode.UNSUPPORTED_SEMANTICS, message))


class ExplicitQualifierCanonicalCompiler:
    """An explicit alternative profile, never the frozen default compiler."""

    @property
    def identity(self):
        return CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE

    @property
    def configuration_cid(self):
        return EXPLICIT_QUALIFIER_CONFIG_CID

    def compile(self, request):
        if not isinstance(request, CompilerRequest):
            raise CanonicalContractError("request must be a bound CompilerRequest")
        if dict(request.config) or request.allow_explicit_partial:
            message = "This opt-in profile accepts no request overrides or partial projection."
            return CompilerResult(OperationStatus.FAILED, request.request_cid,
                                  provenance=_provenance(request, "request_validation"),
                                  error=CanonicalError(CanonicalErrorCode.INVALID_REQUEST, message))
        if len(request.source_text) > MAX_SOURCE_CHARS:
            return _abstain(request, "explicit_qualifier.source_bound", "Source exceeds the profile character bound; no truncation performed.")
        try:
            guard = analyze_canonical_source(request.source_text)
        except ValueError:
            return _abstain(request, "explicit_qualifier.source_guard_bound", "Source guard could not analyze the complete input within its declared bounds.")
        if guard["requires_clarification"]:
            diagnostic = guard["diagnostics"][0]
            return _abstain(request, diagnostic["code"], diagnostic["message"], (diagnostic["start"], diagnostic["end"]))
        try:
            rule = _parse(request.source_text, request.atom_vocabulary)
        except _ParseError as error:
            return _abstain(request, error.code, str(error))
        ir = CanonicalRoundTripIR((rule,))
        source_map = tuple(SourceMapEntry(rule.rule_cid, "/rules/0/" + facet, request.source_cid, 0,
                                          len(request.source_text), "coarse:complete_single_rule_source")
                           for facet in ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal"))
        trace = ComponentTrace(PROFILE, self.identity, request.request_cid, "dag-json", ir.ir_cid, "dag-json",
                               self.configuration_cid, deterministic=True)
        return CompilerResult(OperationStatus.SUCCESS, request.request_cid, canonical_ir=ir, source_map=source_map,
                              provenance=_provenance(request, "complete"), component_trace=(trace,),
                              diagnostics=(CanonicalDiagnostic("explicit_qualifier.complete_source_match",
                                                               "The complete controlled sentence matched caller-declared atoms and connectives.",
                                                               DiagnosticSeverity.INFO),))
