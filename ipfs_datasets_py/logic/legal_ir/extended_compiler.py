"""Opt-in controlled-language compiler for the existing legal surface IR.

Supported profiles consume whole controlled spans. General source prose and
partial matches abstain. Quoted clauses remain uninterpreted atoms. Explicit
typed deadlines are available on norms under a separate profile.
"""
from __future__ import annotations

import json
import re

from ..TDFOL.compiler_repairs import parse_temporal_deadline
from .extended_contracts import (
    DefinitionV2, EffectiveFrom, ExtendedDeadlineLegalIR, ExtendedEffectiveDateLegalIR,
    ExtendedLegalIR, MAX_STATEMENTS, NormV2, PolicyV2,
)
from .extended_decompiler import (
    EFFECTIVE_DATE_PROSE_PROFILE, EXTENDED_REALIZER_PROFILE, MAX_RENDERED_UTF8_BYTES,
    TYPED_DEADLINE_PROSE_PROFILE,
    decompile_extended,
)

_DEADLINE_CLAUSE = re.compile(r"[^.;]+")
_EFFECTIVE_FROM_CLAUSE = re.compile(r"effective from ([0-9]{4}-[0-9]{2}-[0-9]{2})(?=[.;]|$)")


class _ClauseReader:
    def __init__(self, text):
        self.text, self.position = text, 0
        self.decoder = json.JSONDecoder()

    def starts(self, literal):
        return self.text.startswith(literal, self.position)

    def take(self, literal):
        if not self.starts(literal):
            raise ValueError("unsupported controlled-language boundary")
        self.position += len(literal)

    def atom(self):
        if not self.starts('"'):
            raise ValueError("quoted literal required")
        value, self.position = self.decoder.raw_decode(self.text, self.position)
        return value

    def temporal_atom(self):
        if self.starts('"'):
            return self.atom()
        match = _DEADLINE_CLAUSE.match(self.text, self.position)
        deadline = parse_temporal_deadline(match[0]) if match is not None else None
        if deadline is None:
            raise ValueError("unsupported or incomplete explicit typed deadline")
        self.position = match.end()
        return deadline

    def effective_date_atom(self):
        match = _EFFECTIVE_FROM_CLAUSE.match(self.text, self.position)
        if match is None:
            return self.temporal_atom()
        effective = EffectiveFrom(match[1])
        self.position = match.end()
        return effective

    def atoms(self, read_atom=None):
        read_atom = self.atom if read_atom is None else read_atom
        values = [read_atom()]
        while self.starts("; "):
            if len(values) >= MAX_STATEMENTS:
                raise ValueError("clause collection exceeds bound")
            self.take("; ")
            values.append(read_atom())
        return tuple(values)

    def choice(self, spellings):
        for literal, value in spellings:
            if self.starts(literal):
                self.take(literal)
                return value
        raise ValueError("unknown statement operator")


def _statement(text, *, typed_deadlines, typed_effective_dates=False):
    reader = _ClauseReader(text)
    if reader.starts("Norm: "):
        reader.take("Norm: ")
        actor = reader.atom()
        modality = reader.choice(((" must not ", "F"), (" must ", "O"), (" may ", "P")))
        action = reader.atom()
        reader.take(" ")
        values, kind = dict(modality=modality, actor=actor, action=action, object=reader.atom()), NormV2
    elif reader.starts("Definition: "):
        reader.take("Definition: ")
        term = reader.atom()
        relation = reader.choice(tuple((" " + word + " ", word) for word in ("means", "includes", "excludes")))
        values, kind = dict(term=term, relation=relation, meaning=reader.atom()), DefinitionV2
    elif reader.starts("Policy: "):
        reader.take("Policy: ")
        authority = reader.atom()
        stance = reader.choice(((" supports ", "supports"), (" declares as policy ", "declares_policy")))
        values, kind = dict(authority=authority, stance=stance, objectives=reader.atoms()), PolicyV2
    else:
        raise ValueError("unsupported statement kind")
    reader.take(".")
    for field, label in (("scope", "Scope"), ("conditions", "Conditions"),
                         ("exceptions", "Exceptions"), ("temporal", "Temporal")):
        prefix = " " + label + ": "
        if reader.starts(prefix):
            reader.take(prefix)
            read_atom = None
            if kind is NormV2 and field == "temporal":
                if typed_effective_dates:
                    read_atom = reader.effective_date_atom
                elif typed_deadlines:
                    read_atom = reader.temporal_atom
            values[field] = reader.atoms(read_atom)
            reader.take(".")
    if reader.position != len(text):
        raise ValueError("unconsumed or out-of-order source clauses")
    return kind(**values)


def compile_extended(text: str, *, profile: str = EXTENDED_REALIZER_PROFILE) -> ExtendedLegalIR | None:
    """Compile the whole supported controlled span; otherwise abstain.

    The opt-in deadline profile recognizes the complete explicit deadline
    grammar alongside literal slots. Both profiles use only the supplied span.
    """
    if type(profile) is not str or profile not in (
            EXTENDED_REALIZER_PROFILE, TYPED_DEADLINE_PROSE_PROFILE, EFFECTIVE_DATE_PROSE_PROFILE):
        raise ValueError("supported extended prose profile required")
    if type(text) is not str or not text.strip():
        raise ValueError("source must be nonempty text")
    if len(text) > MAX_RENDERED_UTF8_BYTES:
        return None
    try:
        if len(text.encode("utf-8")) > MAX_RENDERED_UTF8_BYTES:
            return None
        lines = text.split("\n", MAX_STATEMENTS)
        if len(lines) > MAX_STATEMENTS:
            return None
        typed_deadlines = profile == TYPED_DEADLINE_PROSE_PROFILE
        typed_effective_dates = profile == EFFECTIVE_DATE_PROSE_PROFILE
        statements = tuple(_statement(line, typed_deadlines=typed_deadlines,
                                      typed_effective_dates=typed_effective_dates) for line in lines)
        if typed_effective_dates:
            ir = ExtendedEffectiveDateLegalIR(statements)
            return ir if decompile_extended(ir, profile=profile) == text else None
        if typed_deadlines:
            ir = ExtendedDeadlineLegalIR(statements)
            return ir if decompile_extended(ir, profile=profile) == text else None
        return ExtendedLegalIR(statements)
    except (ValueError, UnicodeError, RecursionError):
        return None


class _RelationalProseReader(_ClauseReader):
    """Bounded grammar reader building the existing syntax-core AST directly."""

    def __init__(self, text, ast, signatures):
        super().__init__(text)
        self.ast, self.signatures = ast, signatures
        self.serial, self.formulas = 0, 0
        self.sorts, self.predicates, self.roles = {}, {}, {}

    def name(self):
        import re
        found = re.match(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.text[self.position:])
        if found is None:
            raise ValueError("explicit bounded identifier required")
        self.position += len(found[0])
        return found[0]

    def nid(self):
        self.serial += 1
        if self.serial > 1024:
            raise ValueError("complete prose AST node bound exceeded")
        return "prose:node:" + str(self.serial)

    def typed_name(self):
        name = self.name()
        self.take(" of type ")
        sort = self.sorts[self.name()]
        return name, sort

    def variable(self):
        name, sort = self.typed_name()
        return self.ast.mk_variable(self.nid(), name, sort)

    def declarations(self, family, logic_profile):
        self.take("Typed legal rule: " + family + "/" + logic_profile + ".\nTypes: ")
        while True:
            name = self.name()
            if name not in {"Object", "EventFrame", "TimeFrame"} or name in self.sorts:
                raise ValueError("distinct supported atomic type declaration required")
            self.sorts[name] = self.signatures.LogicSort(name)
            if not self.starts(", "):
                break
            self.take(", ")
        self.take(".\n")
        symbols = []
        while self.starts("Predicate "):
            if len(symbols) >= 64:
                raise ValueError("predicate declaration bound exceeded")
            self.take("Predicate ")
            name = self.name()
            self.take(": ")
            if name in self.predicates:
                raise ValueError("duplicate predicate declaration")
            labels, domain = [], []
            while True:
                role, sort = self.typed_name()
                labels.append(role)
                domain.append(sort)
                if len(labels) > 8:
                    raise ValueError("complete ordered predicate arity bound exceeded")
                if not self.starts("; "):
                    break
                self.take("; ")
            self.take(".\n")
            symbol = self.signatures.declare_predicate(name, tuple(domain))
            symbols.append(symbol)
            self.predicates[name], self.roles[name] = symbol, labels
        self.take("Rule: ")
        return self.signatures.LogicSignature("prose:signature", family=family,
            profile=logic_profile, sorts=tuple(self.sorts.values()), symbols=tuple(symbols))

    def sentence(self, depth=0):
        self.formulas += 1
        if self.formulas > 512 or depth > 48:
            raise ValueError("complete prose formula/depth bound exceeded")
        self.take("(")
        ast = self.ast
        if self.starts("for every ") or self.starts("there exists "):
            universal = self.starts("for every ")
            self.take("for every " if universal else "there exists ")
            name, sort = self.typed_name()
            self.take(", " if universal else " such that ")
            body = self.sentence(depth + 1)
            node = (ast.mk_forall if universal else ast.mk_exists)(
                self.nid(), (ast.Binder(name, sort),), body)
        elif self.starts("it is not the case that "):
            self.take("it is not the case that ")
            node = ast.mk_not(self.nid(), self.sentence(depth + 1))
        elif any(self.starts("it is " + word + " that ")
                 for word in ("obligatory", "permitted", "forbidden")):
            word = next(word for word in ("obligatory", "permitted", "forbidden")
                        if self.starts("it is " + word + " that "))
            self.take("it is " + word + " that ")
            letter, kind = {"obligatory": ("O", "obligation"),
                "permitted": ("P", "permission"), "forbidden": ("F", "forbidden")}[word]
            body = self.sentence(depth + 1)
            node = ast.mk_extension(self.nid(), family="tdfol", profile="tdfol_default",
                features=("legacy." + kind, "legacy.classic_letter"),
                payload_schema="legacy.deontic/v1", payload={"kind": kind, "letter": letter,
                    "resolution": "deontic", "schema_version": "legacy.deontic/v1"}, children=(body,))
        elif any(self.starts(word + " (") for word in ("both", "either", "if")):
            word = next(word for word in ("both", "either", "if") if self.starts(word + " ("))
            self.take(word + " ")
            left = self.sentence(depth + 1)
            self.take({"both": " and ", "either": " or ", "if": " then "}[word])
            right = self.sentence(depth + 1)
            node = {"both": ast.mk_and, "either": ast.mk_or, "if": ast.mk_implies}[word](
                self.nid(), left, right)
        elif self.starts("("):
            left = self.sentence(depth + 1)
            self.take(" if and only if ")
            right = self.sentence(depth + 1)
            node = ast.mk_iff(self.nid(), left, right)
        else:
            name = self.name()
            if self.starts(" holds for "):
                self.take(" holds for ")
                symbol = self.predicates[name]
                arguments = []
                for index, role in enumerate(self.roles[name]):
                    if index:
                        self.take("; ")
                    self.take(role + ": ")
                    arguments.append(self.variable())
                if tuple(child.sort for child in arguments) != symbol.domain:
                    raise ValueError("predicate argument types differ from declared ordered types")
                node = ast.mk_predicate(self.nid(), name, tuple(arguments))
            else:
                self.take(" of type ")
                sort = self.sorts[self.name()]
                left = ast.mk_variable(self.nid(), name, sort)
                self.take(" is identical to ")
                node = ast.mk_equality(self.nid(), left, self.variable())
        self.take(")")
        return node


def compile_relational(text: str, *, profile: str, capacity_profile=None):
    """Parse one entire supported controlled legal span, or abstain as a whole.

    The result is ``(TypedExpression, argument_roles)`` using the existing AST.
    No reference target, original wording, serialized AST, source cache or caller
    signature is available to this inverse. Declaration/scope/type mismatches,
    unsupported clauses and every unconsumed character refuse the whole input.
    """
    from .extended_decompiler import (RELATIONAL_PROSE_PROFILE, COUNTED_PROSE_PROFILE,
        PARAMETRIC_COUNTED_PROSE_PROFILE,
        _COUNTED_PROSE_SENTENCE, _prose_capacity_options, decompile_relational)

    if type(profile) is not str or profile not in (
            RELATIONAL_PROSE_PROFILE, COUNTED_PROSE_PROFILE, PARAMETRIC_COUNTED_PROSE_PROFILE):
        raise ValueError("explicit supported relational prose profile required")
    capacity_options = _prose_capacity_options(profile, capacity_profile)
    if type(text) is not str or not text.strip():
        raise ValueError("source must be nonempty text")
    if len(text) > MAX_RENDERED_UTF8_BYTES:
        return None
    try:
        if len(text.encode("utf-8")) > MAX_RENDERED_UTF8_BYTES:
            return None
        from ..syntax_core import ast, signatures
        reader = _RelationalProseReader(text, ast, signatures)
        family, logic_profile = (("first_order", "many_sorted") if profile in (
                                    COUNTED_PROSE_PROFILE, PARAMETRIC_COUNTED_PROSE_PROFILE)
                                 else ("tdfol", "tdfol_default"))
        signature = reader.declarations(family, logic_profile)
        if profile == PARAMETRIC_COUNTED_PROSE_PROFILE:
            from ..autoformal import legal_counted_frame_threshold_v2 as threshold
            prefix, suffix = _COUNTED_PROSE_SENTENCE.split("3", 1)
            reader.take(prefix)
            number = re.match(r"(?:0|[1-9][0-9]*)", reader.text[reader.position:])
            if number is None:
                return None
            reader.position += len(number[0])
            reader.take(suffix)
            fixed, _ = threshold._parametric_expression(ast, signatures, int(number[0]), **capacity_options)
            root, signature = fixed.root, fixed.signature
        elif profile == COUNTED_PROSE_PROFILE:
            from ..autoformal import legal_counted_frame_v1 as counted
            reader.take(_COUNTED_PROSE_SENTENCE)
            fixed = counted._fixed_expression(ast, signatures)
            root = fixed.root
            # Visible declarations are checked by complete canonical readback;
            # retain the canonical counted owner's signature declaration order.
            signature = fixed.signature
        else:
            root = reader.sentence()
        reader.take(".")
        if reader.position != len(text):
            return None
        expression = ast.TypedExpression("prose:expression", root, signature)
        roles = [{"symbol": name, "roles": list(reader.roles[name])} for name in sorted(reader.roles)]
        # This reuses the complete canonical-fragment validator and also rejects
        # alternate spelling/order rather than repair, truncate or silently skip.
        if decompile_relational(expression, argument_roles=roles, profile=profile, **capacity_options) != text:
            return None
        return expression, roles
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return None
