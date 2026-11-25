"""Deterministic source-withheld realization of the opt-in surface IR.

This controlled legal language preserves every literal slot and statement kind.
It interprets no opaque clause, quantifier, calendar, definition applicability or
statutory meaning. The measured canonical v1 realizer remains a separate owner.
"""
from __future__ import annotations

import json

from ..TDFOL.compiler_repairs import render_temporal_deadline
from .extended_contracts import (
    DefinitionV2, EffectiveFrom, ExtendedDeadlineLegalIR, ExtendedEffectiveDateLegalIR,
    ExtendedLegalIR, NormV2, PolicyV2,
)

EXTENDED_REALIZER_PROFILE = "source-withheld-quoted-legal-clauses/v2"
TYPED_DEADLINE_PROSE_PROFILE = "source-withheld-typed-legal-deadlines/v1"
EFFECTIVE_DATE_PROSE_PROFILE = "source-withheld-typed-legal-effective-dates/v1"
MAX_RENDERED_UTF8_BYTES = 1024 * 1024


def decompile_extended(ir: ExtendedLegalIR, *, profile: str = EXTENDED_REALIZER_PROFILE) -> str:
    """Render the complete typed value, or refuse without truncating clauses.

    Only the supplied semantic slots enter the output. No source, receipt,
    identity, cache, model or original-wording channel is accepted. Collection
    order and duplicates remain visible; clause lists do not invent logical
    conjunction/disjunction or decide the applicability of a definition.
    """
    if type(profile) is not str or profile not in (
            EXTENDED_REALIZER_PROFILE, TYPED_DEADLINE_PROSE_PROFILE, EFFECTIVE_DATE_PROSE_PROFILE):
        raise ValueError("supported extended prose profile required")
    expected = {EXTENDED_REALIZER_PROFILE: ExtendedLegalIR,
                TYPED_DEADLINE_PROSE_PROFILE: ExtendedDeadlineLegalIR,
                EFFECTIVE_DATE_PROSE_PROFILE: ExtendedEffectiveDateLegalIR}[profile]
    if type(ir) is not expected:
        raise ValueError("extended IR type differs from selected prose profile")
    ExtendedLegalIR.__post_init__(ir)
    parts, size = [], 0

    def write(value):
        nonlocal size
        try:
            size += len(value.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("extended realization requires valid UTF-8 literals") from error
        if size > MAX_RENDERED_UTF8_BYTES:
            raise ValueError("complete extended realization exceeds UTF-8 byte bound; truncation refused")
        parts.append(value)

    def atom(value):
        write(json.dumps(value, ensure_ascii=False))

    def atoms(values):
        for index, value in enumerate(values):
            if index:
                write("; ")
            if type(value) is str:
                atom(value)
            elif type(value) is EffectiveFrom:
                write("effective from " + value.effective_from)
            else:
                write(render_temporal_deadline(value))

    for index, statement in enumerate(ir.statements):
        if index:
            write("\n")
        if type(statement) is NormV2:
            write("Norm: ")
            atom(statement.actor)
            write(" " + {"O": "must", "P": "may", "F": "must not"}[statement.modality] + " ")
            atom(statement.action)
            write(" ")
            atom(statement.object)
        elif type(statement) is DefinitionV2:
            write("Definition: ")
            atom(statement.term)
            write(" " + statement.relation + " ")
            atom(statement.meaning)
        elif type(statement) is PolicyV2:
            write("Policy: ")
            atom(statement.authority)
            write(" " + {"supports": "supports", "declares_policy": "declares as policy"}[statement.stance] + " ")
            atoms(statement.objectives)
        else:
            raise ValueError("unsupported extended statement type")
        write(".")
        for field, label in (("scope", "Scope"), ("conditions", "Conditions"),
                             ("exceptions", "Exceptions"), ("temporal", "Temporal")):
            values = getattr(statement, field)
            if values:
                write(" " + label + ": ")
                atoms(values)
                write(".")
    return "".join(parts)


# Separate opt-in contracts: these do not widen the literal-slot v2 default.
RELATIONAL_PROSE_PROFILE = "source-withheld-typed-relational-legal-prose/v1"
COUNTED_PROSE_PROFILE = "source-withheld-fixed-three-counted-legal-prose/v1"
PARAMETRIC_COUNTED_PROSE_PROFILE = "source-withheld-authored-parametric-counted-legal-prose/v1"
_COUNTED_PROSE_SENTENCE = (
    "(for each event of type EventFrame and time of type TimeFrame, "
    "at most 3 distinct objects of type Object satisfy Member with "
    "object: the object; event: event; time: time)"
)


def _prose_capacity_options(profile, capacity_profile):
    """Select only the existing explicit counted capacity; keep legacy calls exact."""
    if capacity_profile is None:
        return {}
    if type(profile) is not str or profile != PARAMETRIC_COUNTED_PROSE_PROFILE:
        raise ValueError("explicit capacity requires the authored parametric counted prose profile")
    from ..autoformal import legal_counted_frame_threshold_v2 as threshold
    threshold._parametric_capacity(capacity_profile)
    return {"capacity_profile": capacity_profile}


def _prose_capacity_json(value, *, capacity_profile, maximum=None, detached=False):
    """Reuse the existing preservation codec under the exact selected finite bounds."""
    from ..autoformal import legal_counted_frame_threshold_v2 as threshold
    if capacity_profile is None:
        raise ValueError("explicit existing counted capacity required")
    capacities = threshold._parametric_capacity(capacity_profile)
    maximum = capacities["max_bytes"] if maximum is None else maximum
    if type(maximum) is not int or not 0 < maximum <= capacities["max_bytes"]:
        raise ValueError("bounded selected parametric JSON byte capacity required")
    owner = threshold._parametric_capacity_owner()
    bounds = {"max_json_depth": capacities["max_json_depth"],
              "max_json_items": capacities["max_json_items"]}
    raw = owner._wire(value, maximum, **bounds)
    return owner._parse(raw, maximum, **bounds) if detached else raw


def _parametric_counted_value(expression, *, capacity_profile=None):
    """Recognize the complete existing authored threshold form, modulo transport IDs.

    This is a bounded syntax recognizer, not a legal or semantic-equivalence proof.
    Binder names, ordering, sorts, membership arguments and every equality remain
    exact. Reuse the producer's finite preflight before expanding any expectation.
    """
    from ..syntax_core import ast, signatures
    from ..autoformal import legal_counted_frame_threshold_v2 as threshold
    from ..autoformal.legal_relational_reconstruction_v1 import _prose_typed_projection

    capacity_options = _prose_capacity_options(PARAMETRIC_COUNTED_PROSE_PROFILE, capacity_profile)
    maximum = -3  # event, time, and maximum + 1 object binders
    node = expression.root
    while node.kind is ast.NodeKind.FORALL:
        if len(node.binders) != 1 or len(node.arguments) != 1:
            raise ValueError("complete authored counted threshold binders required")
        maximum += 1
        node = node.arguments[0]
    expected, _ = threshold._parametric_expression(ast, signatures, maximum, **capacity_options)
    if _prose_typed_projection(expression, **capacity_options) != _prose_typed_projection(expected, **capacity_options):
        raise ValueError("complete authored counted threshold structure required")
    return maximum


def _relational_prose_input(expression, argument_roles, profile, *, capacity_profile=None):
    """Reuse canonical authored-fragment validation, without a native operation.

    No original text, source binding, source range or arbitrary metadata channel
    is accepted. Identifiers are predicate/type/variable names, not prose slots.
    The existing relational profiles require all predicates to occur, one binder
    per quantifier, and globally distinct binders; unsupported declarations are
    refused in their entirety rather than dropped from the realization.
    """
    from ..syntax_core import ast, signatures
    from ..autoformal import legal_relational_norm_v1 as relational

    capacity_options = _prose_capacity_options(profile, capacity_profile)
    if type(expression) is not ast.TypedExpression:
        raise ValueError("canonical TypedExpression required")
    if type(profile) is not str or profile not in (
            RELATIONAL_PROSE_PROFILE, COUNTED_PROSE_PROFILE, PARAMETRIC_COUNTED_PROSE_PROFILE):
        raise ValueError("explicit supported relational prose profile required")
    if type(argument_roles) is not list:
        raise ValueError("complete ordinary ordered argument role ledger required")
    try:
        request = {"expression": expression.to_dict(), "argument_roles": argument_roles}
        if capacity_options:
            _prose_capacity_json(request, **capacity_options)
        else:
            relational._wire(request, relational.MAX_REQUEST_BYTES)
    except (TypeError, KeyError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded complete typed expression and roles required") from error
    if profile == PARAMETRIC_COUNTED_PROSE_PROFILE:
        if argument_roles != [{"symbol": "Member", "roles": ["object", "event", "time"]}]:
            raise ValueError("exact counted membership roles required")
        _parametric_counted_value(expression, **capacity_options)
        return expression, {"Member": ["object", "event", "time"]}
    if profile == COUNTED_PROSE_PROFILE:
        from ..autoformal import legal_counted_frame_v1 as counted
        counted._preflight_expression(request["expression"])
        checked, _, _ = counted._recognize(request, ast, signatures)
        if argument_roles != [{"symbol": "Member", "roles": ["object", "event", "time"]}]:
            raise ValueError("exact counted membership roles required")
        return checked, {"Member": ["object", "event", "time"]}
    if len(expression.signature.sorts) == 2:
        checked, _ = relational._strict_expression(request, ast, signatures)
    else:
        checked, _, _ = relational._mixed_strict_expression(request, ast, signatures)
    return checked, {row["symbol"]: list(row["roles"]) for row in argument_roles}


def decompile_relational(expression, *, argument_roles, profile: str, capacity_profile=None) -> str:
    """Realize the complete supported typed structure as controlled legal prose.

    This source-withheld interface receives only an existing TypedExpression and
    its complete declared argument roles. O/P/F are explicit modal operators,
    not observations of compliance. Conditions and exceptions retain their
    Boolean/negation scope; no legal applicability or modal axioms are inferred.
    The legacy count profile recognizes only the existing fixed-three expansion.
    The separate authored parametric profile retains the producer's current finite
    AST/depth/byte limits and refuses other syntax instead of dropping clauses.
    The relational profile also retains supported generic quantifier/equality
    expansions, without assigning them a new counting interpretation.
    """
    from ..syntax_core import ast, signatures
    from ..autoformal import legal_relational_norm_v1 as relational

    capacity_options = _prose_capacity_options(profile, capacity_profile)
    checked, roles = _relational_prose_input(expression, argument_roles, profile, **capacity_options)
    predicates = {symbol.name: symbol for symbol in checked.signature.symbols}
    seen_ids, seen_binders, used = set(), set(), set()
    node_count = 0

    def visit(node, bound, depth):
        nonlocal node_count
        node_count += 1
        if (node_count > relational.MAX_NODES or depth > relational.MAX_DEPTH
                or type(node) is not ast.LogicNode or node.node_id in seen_ids
                or node.metadata or node.range is not None
                or not isinstance(node.kind, ast.NodeKind)):
            raise ValueError("unsupported or unbounded complete relational node")
        seen_ids.add(node.node_id)
        kind = node.kind.value
        if kind == "variable":
            relational._safe_name(node.symbol)
            if node.symbol not in bound or node.sort != bound[node.symbol]:
                raise ValueError("explicitly bound same-sort variable required")
            return node.symbol + " of type " + node.sort.name
        if node.sort != signatures.BOOL_SORT:
            raise ValueError("formula Bool sort required")
        if kind == "predicate":
            if node.symbol not in predicates:
                raise ValueError("declared predicate required")
            symbol = predicates[node.symbol]
            if (len(node.arguments) != symbol.arity
                    or any(child.kind is not ast.NodeKind.VARIABLE for child in node.arguments)
                    or tuple(child.sort for child in node.arguments) != symbol.domain):
                raise ValueError("complete ordered typed variable arguments required")
            used.add(node.symbol)
            values = [role + ": " + visit(child, bound, depth + 1)
                      for role, child in zip(roles[node.symbol], node.arguments, strict=True)]
            return "(" + node.symbol + " holds for " + "; ".join(values) + ")"
        if kind == "equality":
            if (len(node.arguments) != 2
                    or any(child.kind is not ast.NodeKind.VARIABLE for child in node.arguments)
                    or node.arguments[0].sort != node.arguments[1].sort):
                raise ValueError("same-sort bound-variable equality required")
            return "(" + visit(node.arguments[0], bound, depth + 1) + " is identical to " + visit(
                node.arguments[1], bound, depth + 1) + ")"
        if kind in {"and", "or", "implies", "iff"}:
            if len(node.arguments) != 2:
                raise ValueError("exact binary connective required; no flattening")
            left, right = (visit(child, bound, depth + 1) for child in node.arguments)
            prefix, middle = {"and": ("both ", " and "), "or": ("either ", " or "),
                "implies": ("if ", " then "), "iff": ("", " if and only if ")}[kind]
            return "(" + prefix + left + middle + right + ")"
        if kind == "not":
            return "(it is not the case that " + visit(node.arguments[0], bound, depth + 1) + ")"
        if kind in {"forall", "exists"}:
            if len(node.binders) != 1:
                raise ValueError("exactly one binder per quantifier required")
            binder = node.binders[0]
            relational._safe_name(binder.name)
            if (binder.name in seen_binders or binder.name in predicates
                    or binder.sort.name not in {"Object", "EventFrame", "TimeFrame"}):
                raise ValueError("globally distinct nonshadowing typed binder required")
            seen_binders.add(binder.name)
            body = visit(node.arguments[0], {**bound, binder.name: binder.sort}, depth + 1)
            phrase = ("for every " + binder.name + " of type " + binder.sort.name + ", "
                if kind == "forall" else "there exists " + binder.name + " of type "
                + binder.sort.name + " such that ")
            return "(" + phrase + body + ")"
        if kind == "extension":
            extension = node.extension
            if (type(extension) is not ast.LogicExtensionNode or extension.node_id in seen_ids
                    or node.arguments or node.binders or node.symbol
                    or extension.family != checked.family or extension.profile != checked.profile
                    or extension.payload_schema != "legacy.deontic/v1" or extension.metadata
                    or extension.range is not None or len(extension.children) != 1
                    or not extension.children[0].is_formula):
                raise ValueError("only exact unannotated O/P/F extension supported")
            seen_ids.add(extension.node_id)
            letter = extension.payload.get("letter")
            kinds = {"O": "obligation", "P": "permission", "F": "forbidden"}
            if (type(letter) is not str or letter not in kinds
                    or dict(extension.payload) != {"kind": kinds[letter], "letter": letter,
                        "resolution": "deontic", "schema_version": "legacy.deontic/v1"}
                    or set(extension.features) != {"legacy." + kinds[letter], "legacy.classic_letter"}):
                raise ValueError("exact independent O/P/F payload and features required")
            word = {"O": "obligatory", "P": "permitted", "F": "forbidden"}[letter]
            return "(it is " + word + " that " + visit(extension.children[0], bound, depth + 1) + ")"
        raise ValueError("unsupported relational construct; whole realization refused")

    if profile == PARAMETRIC_COUNTED_PROSE_PROFILE:
        maximum = _parametric_counted_value(checked, **capacity_options)
        body = _COUNTED_PROSE_SENTENCE.replace("at most 3 distinct", "at most " + str(maximum) + " distinct", 1)
    elif profile == COUNTED_PROSE_PROFILE:
        body = _COUNTED_PROSE_SENTENCE
    else:
        body = visit(checked.root, {}, 0)
        if used != set(predicates) or not seen_binders:
            raise ValueError("all declarations must occur in a closed quantified rule")
    lines = ["Typed legal rule: " + checked.family.value + "/" + checked.profile.value + ".",
             "Types: " + ", ".join(sorted(sort.name for sort in checked.signature.sorts
                                           if not sort.is_bool)) + "."]
    for name in sorted(predicates):
        values = [role + " of type " + sort.name for role, sort in zip(
            roles[name], predicates[name].domain, strict=True)]
        lines.append("Predicate " + name + ": " + "; ".join(values) + ".")
    lines.append("Rule: " + body + ".")
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > MAX_RENDERED_UTF8_BYTES:
        raise ValueError("complete relational prose exceeds bound; truncation refused")
    return text
