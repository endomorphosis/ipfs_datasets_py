"""Versioned bounded Intent syntax; training labels and post-inference checks.

This parser is never a replacement for learned predictions. Its explicit
source grammar supplies weak training supervision and checks complete model
outputs after inference. No parser slots are passed to the neural encoder.
"""
from __future__ import annotations

import re

SCHEMA = "intent-rich-grammar/v1"
MODALS = {"intended":"intends to", "required":"must", "prohibited":"must not",
          "permitted":"may", "recommended":"should"}
SURFACES = {"intends to":"intended", "must":"required", "shall":"required",
    "must not":"prohibited", "shall not":"prohibited", "do not":"prohibited", "never":"prohibited",
    "may":"permitted", "should":"recommended", "is required to":"required",
    "is forbidden to":"prohibited", "is allowed to":"permitted"}
_ATOM = r"[A-Za-z][A-Za-z0-9_-]*"
_WORD = re.compile(_ATOM + r"\Z")
_SLOT = re.compile(r"[A-Za-z0-9_./:`-]+(?: [A-Za-z0-9_./:`-]+)*\Z")
_UNSUPPORTED = frozenset("unless until before after while once whenever wherever assuming provided given because whether whereas since notwithstanding except without otherwise meanwhile subsequently finally each every all any either neither both none no some a an only always eventually exactly least most whose which whom".split())
_REFERENCES = frozenset("i me my mine myself you your yours yourself yourselves we us our ours ourselves he him his himself she her hers herself it its itself they them their theirs themselves this that these those former latter above below previous same such here there".split())
_GRAMMAR_WORDS = frozenset("and or then if must shall may should not never intends is are was were be been being has have had does did can could would will to".split())


def _slot(value, maximum=160, words=16):
    if (type(value) is not str or not 0 < len(value) <= maximum or len(value.split()) > words
            or not _SLOT.fullmatch(value) or "  " in value or value.count('`') % 2):
        raise ValueError("bounded case-preserving lexical slot required")
    return value


def validate_ast(ast):
    if type(ast) is not dict:
        raise ValueError("closed rich Intent AST required")
    kind = ast.get("kind")
    if type(kind) is not str:
        raise ValueError("declared rich constructor required")
    if kind == "atom" and set(ast) == {"kind","actor","action","object","modality"}:
        _slot(ast["actor"], words=4); _slot(ast["object"])
        if (type(ast['action']) is not str or not _WORD.fullmatch(ast["action"])
                or ast["action"] != ast["action"].lower() or type(ast['modality']) is not str or ast["modality"] not in MODALS):
            raise ValueError("stable action and declared modality required")
    elif kind in {"and","or","then"} and set(ast) == {"kind","left","right"}:
        for key in ("left","right"):
            if type(ast[key]) is not dict or ast[key].get("kind") != "atom":
                raise ValueError("first rich grammar permits only two atomic branches")
            validate_ast(ast[key])
    elif kind == "if" and set(ast) == {"kind","guard","body"}:
        guard = ast["guard"]
        if (type(guard) is not dict or set(guard) != {"subject","property","negated"}
                or type(guard["negated"]) is not bool):
            raise ValueError("closed atomic condition required")
        _slot(guard["subject"], words=4)
        if (type(guard["property"]) is not str or not _WORD.fullmatch(guard["property"])
                or guard['property'].lower() in _GRAMMAR_WORDS | _UNSUPPORTED | _REFERENCES):
            raise ValueError("atomic guard property required")
        if type(ast['body']) is not dict or ast["body"].get("kind") != "atom":
            raise ValueError("one guarded atomic norm required")
        validate_ast(ast["body"])
    else:
        raise ValueError("unsupported rich Intent constructor or fields")
    return ast


def ast_to_sequence(ast):
    validate_ast(ast)
    kind = ast["kind"]
    if kind == "atom":
        return " ".join(f"<{key}> {ast[key]}" for key in ("actor","action","object","modality"))
    if kind in {"and","or","then"}:
        return f"<{kind}> {ast_to_sequence(ast['left'])} <next> {ast_to_sequence(ast['right'])}"
    guard = ast["guard"]
    return (f"<if> {guard['subject']} <property> {guard['property']} "
            f"<polarity> {'negative' if guard['negated'] else 'positive'} <body> {ast_to_sequence(ast['body'])}")


def _unspace(value):
    value = " ".join(value.split())
    value = re.sub(r"\s*([./:_-])\s*",r"\1",value)
    return re.sub(r"`\s*([^`]+?)\s*`", lambda m:'`'+m[1]+'`',value)


def sequence_to_ast(text):
    if type(text) is not str or not 0 < len(text) <= 4096:
        raise ValueError("bounded predicted rich sequence required")
    text = text.strip()
    binary = re.fullmatch(r"<(and|or|then)>\s+(.+?)\s+<next>\s+(.+)",text)
    guard = re.fullmatch(r"<if>\s+([^<>]+?)\s+<property>\s+([^<>]+?)\s+<polarity>\s+(positive|negative)\s+<body>\s+(.+)",text)
    if binary:
        value = {"kind":binary[1],"left":sequence_to_ast(binary[2]),"right":sequence_to_ast(binary[3])}
    elif guard:
        value = {"kind":"if","guard":{"subject":_unspace(guard[1]),"property":_unspace(guard[2]),
            "negated":guard[3]=="negative"},"body":sequence_to_ast(guard[4])}
    else:
        match = re.fullmatch(r"<actor>\s+([^<>]+?)\s+<action>\s+([^<>]+?)\s+<object>\s+([^<>]+?)\s+<modality>\s+([^<>]+?)",text)
        if not match:
            raise ValueError("invalid rich decoder production sequence")
        value = {"kind":"atom",**{key:_unspace(item) for key,item in zip(("actor","action","object","modality"),match.groups())}}
    return validate_ast(value)


def ast_to_text(ast):
    validate_ast(ast)
    kind = ast["kind"]
    if kind == "atom":
        return f"{ast['actor']} {MODALS[ast['modality']]} {ast['action']} {ast['object']}."
    if kind in {"and","or","then"}:
        return ast_to_text(ast['left'])[:-1]+" "+kind+" "+ast_to_text(ast['right'])
    g = ast['guard']
    return f"if {g['subject']} is {'not ' if g['negated'] else ''}{g['property']}, {ast_to_text(ast['body'])}"


def _without_article(value):
    return value[4:] if value.startswith("the ") else value


def _leaf(text, *, normalized_inverse=False):
    from .instruction_scope import _BARE_ACTIONS
    actor, modality, body = "unspecified", "intended", text
    modal_alts = "|".join(re.escape(x) for x in sorted(SURFACES,key=len,reverse=True))
    explicit = re.fullmatch(r"(.+?) ("+modal_alts+r") (.+)",text)
    if explicit:
        actor, modal, body = explicit.groups()
        actor = _without_article(actor)
        modality = SURFACES[modal]
        _slot(actor, words=4)
        if set(actor.lower().split()) & (_UNSUPPORTED | _REFERENCES | _GRAMMAR_WORDS):
            raise ValueError("unresolved actor scope")
    else:
        if normalized_inverse:
            raise ValueError("inverse must state actor and modality")
        if text.startswith("please "):
            body = text[7:]
        for modal in sorted(SURFACES,key=len,reverse=True):
            if body.startswith(modal+" "):
                modality, body = SURFACES[modal], body[len(modal)+1:]
                break
    parts = body.split(" ",1)
    if len(parts)!=2:
        raise ValueError("complete action and object required")
    action, obj = parts[0].lower(), _without_article(parts[1])
    reserved_actions = _UNSUPPORTED | _REFERENCES | _GRAMMAR_WORDS
    if (not _WORD.fullmatch(action) or action in reserved_actions
            or (action not in _BARE_ACTIONS and explicit is None)):
        raise ValueError("unclassified action")
    words = set(obj.lower().replace('`','').split())
    if words & (_UNSUPPORTED | _REFERENCES | {"and","or","then","if","must","shall","may","should","not","to","is","are","was","were","be","been","being","has","have","had","come","analyzed"}):
        raise ValueError("object contains unsupported scope or predication")
    # These are noun fragments in the source corpus; requesting that they be
    # forced through the decoder would create spurious imperative intent.
    if action == "benchmark" and obj.lower().startswith("suite for "):
        raise ValueError("ambiguous descriptive noun phrase")
    return validate_ast({"kind":"atom","actor":actor,"action":action,"object":obj,"modality":modality})


def parse_instruction(instruction, *, normalized_inverse=False):
    """Whole-input bounded grammar, for weak labels and independent agreement."""
    if (type(instruction) is not str or not instruction.strip() or len(instruction)>4096
            or not instruction.isascii() or any(c in instruction for c in "\n\r<>?!;()[]{}")):
        raise ValueError("source outside bounded rich grammar")
    text = " ".join(instruction.strip().split()).removesuffix(".")
    if re.search(r"\.\s+",text):
        raise ValueError("multiple sentences require document routing")
    # Only initial grammatical capitalization is normalized. Slot case survives.
    for lead in ("The ","If ","Please ","Do not ","Never ","Must ","Should ","May "):
        if text.startswith(lead):
            text = lead[0].lower()+text[1:]
            break
    conditional = re.fullmatch(r"if (.+?) is (not )?("+_ATOM+r"), (.+)",text)
    if conditional:
        subject, negative, prop, body = conditional.groups()
        subject = _without_article(subject)
        if set(subject.lower().split()) & (_UNSUPPORTED | _REFERENCES | _GRAMMAR_WORDS):
            raise ValueError("unresolved guard subject")
        return validate_ast({"kind":"if","guard":{"subject":subject,"property":prop,"negated":bool(negative)},
                             "body":_leaf(body,normalized_inverse=normalized_inverse)})
    if text.startswith('if ') or ',' in text:
        raise ValueError("unsupported conditional or list scope")
    for surface, kind in ((" and then ","then"),(" then ","then"),(" and ","and"),(" or ","or")):
        if surface in text:
            left, right = text.split(surface,1)
            a, b = _leaf(left,normalized_inverse=normalized_inverse), _leaf(right,normalized_inverse=normalized_inverse)
            if a['actor']!='unspecified' and b['actor']=='unspecified':
                raise ValueError("implicit shared actor or modal scope requires explicit branches")
            if (a['modality']!='intended' and b['actor']=='unspecified'
                    and not any(right.startswith(m+' ') for m in SURFACES)):
                raise ValueError("shared leading modality requires explicit branch scope")
            return validate_ast({"kind":kind,"left":a,"right":b})
    return _leaf(text,normalized_inverse=normalized_inverse)


def model_input(instruction):
    """Normalize initial grammar capitalization while retaining every slot byte.

    Predicate/identifier case is untouched. This transform exports no semantic
    slots and is applied equally to training and numerical source inference.
    """
    from .instruction_scope import _BARE_ACTIONS
    text=' '.join(instruction.split())
    first,separator,rest=text.partition(' ')
    cues={'the','if','please','do','never','must','shall','should','may'}
    explicit_actor=any(' '+surface+' ' in text for surface in SURFACES)
    if first.lower() in cues or (first.lower() in _BARE_ACTIONS and not explicit_actor):
        first=first.lower()
    return first+separator+rest


__all__ = ["SCHEMA","MODALS","validate_ast","ast_to_sequence","sequence_to_ast","ast_to_text","parse_instruction"]
