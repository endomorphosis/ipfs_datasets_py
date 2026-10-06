"""Render closed grouped semantic IR without access to original legal source.

Requests contain only ordered actor/modality/action labels and explicit scope
choices. They carry no source text, provenance, formula, AST, or teacher output.
This deterministic renderer establishes a target interface for future learned
predictions; successful rendering is not evidence of legal semantic accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from ..formalization.autoencoder import native_family_lean_emitters as emitters
from ..intent_ir.formalize.modal_projections import _ast
from ..autoformal import family_qualification as qualification

COORDINATION_DECODE_REQUEST_SCHEMA = "legal-coordination-decode-request/v1"
COORDINATION_DECODE_RESULT_SCHEMA = "legal-coordination-decode-result/v1"
MAX_DECODE_MEMBERS = 8
MAX_ACTOR_CHARACTERS = 256
MAX_ACTION_CHARACTERS = 1024

_MEMBER_FIELDS = {"actor", "modality", "action"}
_REQUEST_FIELDS = {"schema", "modal_scope", "connective", "binding_profile", "members"}
_CHOICES = {
    "modal_scope": {"modal_over_actions", "disjunction_of_norms"},
    "connective": {"inclusive_or"},
    "binding_profile": {"universal_actor_predicate"},
}
_WORDS_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*(?:[ \t]+[A-Za-z0-9][A-Za-z0-9'’\-]*)*")
_ACTOR_FORBIDDEN_RE = re.compile(
    r"\b(?:and|or|nor|but|either|neither|no|none|not|each|every|all|any|some|such)\b",
    re.IGNORECASE,
)
_ACTION_FORBIDDEN_RE = re.compile(r"\b(?:and|or|nor|but|either|neither|not|never|no|none)\b", re.IGNORECASE)
_MODAL_RE = re.compile(
    r"\b(?:shall|must|may|cannot|can|will|should|might)\b|"
    r"\b(?:is|are)\s+(?:(?:legally|hereby)\s+)*(?:required|authorized|permitted|entitled|prohibited|forbidden|obligated|"
    r"responsible|accountable|answerable|tasked|entrusted|liable|bound|directed|instructed|"
    r"ordered|mandated|commanded|empowered|designated|appointed|charged|assigned|vested|"
    r"granted|delegated|conferred|compelled|duty[ -]bound|unlawful|illegal)\b|"
    r"\b(?:has|have|owes|owe|bears|bear)\s+(?:(?:a|an|the)\s+)?(?:duty|responsibility|obligation|authority|power)\b|"
    r"\brequired\s+to\b", re.IGNORECASE,
)
_QUALIFIER_RE = re.compile(
    r"\b(?:if|unless|except|when|where|provided|who|which|that|until|once|while|because|whether|"
    r"before|after|during|within|without|absent|notwithstanding|pursuant|under|upon|following|"
    r"pending|subject\s+to|according\s+to|in\s+accordance\s+with|in\s+case|in\s+the\s+event|"
    r"annually|monthly|weekly|daily|immediately|promptly|subsequently|previously|simultaneously|"
    r"then|whenever|section|sections|subsection|subsections|paragraph|paragraphs|chapter|chapters|"
    r"by\s+\d|on\s+\d)\b", re.IGNORECASE,
)
_DIGEST_RE = re.compile(r"\b[a-f0-9]{32,}\b|\b[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\b", re.IGNORECASE)


def _exact_fields(value: Any, fields: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"Exact {name} fields required; provenance and teacher fields are forbidden")


def _validate_label(value: Any, *, actor: bool) -> None:
    limit = MAX_ACTOR_CHARACTERS if actor else MAX_ACTION_CHARACTERS
    words = 12 if actor else 32
    if (type(value) is not str or not 0 < len(value) <= limit
            or len(value.split()) > words or not _WORDS_RE.fullmatch(value)):
        raise ValueError("Bounded lexical semantic labels required")
    if (_MODAL_RE.search(value) or _QUALIFIER_RE.search(value) or _DIGEST_RE.search(value)
            or (_ACTOR_FORBIDDEN_RE if actor else _ACTION_FORBIDDEN_RE).search(value)):
        raise ValueError("Semantic labels cannot embed modal, qualifier, source, or compound structure")
    if not semantic_label_identity(value, actor=actor):
        raise ValueError("Semantic label identity cannot be blank")


def semantic_label_identity(text: str, *, actor: bool) -> str:
    """Normalize labels only: case/spacing, plus one actor-leading article.

    No synonym inference or actor identity resolution occurs. Hyphens and
    apostrophes remain significant; in particular ``a-b`` and ``a b`` differ.
    """
    if type(text) is not str:
        raise ValueError("Semantic label must be a string")
    text = " ".join(text.split()).casefold()
    return text.removeprefix("the ") if actor else text


@dataclass(frozen=True, slots=True)
class CoordinationDecodeMember:
    actor: str
    modality: str
    action: str

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if type(self) is not CoordinationDecodeMember:
            raise ValueError("Exact typed coordination decode member required")
        _validate_label(self.actor, actor=True)
        _validate_label(self.action, actor=False)
        if type(self.modality) is not str or self.modality not in {"O", "P", "F"}:
            raise ValueError("Member modality must be O, P, or F")

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {"actor": self.actor, "modality": self.modality, "action": self.action}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CoordinationDecodeMember:
        _exact_fields(value, _MEMBER_FIELDS, "coordination decode member")
        return cls(actor=value["actor"], modality=value["modality"], action=value["action"])


@dataclass(frozen=True, slots=True)
class CoordinationDecodeRequest:
    modal_scope: str
    connective: str
    binding_profile: str
    members: tuple[CoordinationDecodeMember, ...]
    schema: str = COORDINATION_DECODE_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if type(self) is not CoordinationDecodeRequest:
            raise ValueError("Exact typed coordination decode request required")
        if type(self.schema) is not str or self.schema != COORDINATION_DECODE_REQUEST_SCHEMA:
            raise ValueError("Unsupported coordination decode request schema")
        for field, allowed in _CHOICES.items():
            value = getattr(self, field)
            if type(value) is not str or value not in allowed:
                raise ValueError(f"Explicit supported {field} required")
        if (type(self.members) is not tuple or not 2 <= len(self.members) <= MAX_DECODE_MEMBERS
                or any(type(member) is not CoordinationDecodeMember for member in self.members)):
            raise ValueError("Two through eight ordered immutable decode members required")
        for member in self.members:
            member.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "modal_scope": self.modal_scope,
                "connective": self.connective, "binding_profile": self.binding_profile,
                "members": [member.to_dict() for member in self.members]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CoordinationDecodeRequest:
        _exact_fields(value, _REQUEST_FIELDS, "coordination decode request")
        members = value["members"]
        if type(members) is not list or not 2 <= len(members) <= MAX_DECODE_MEMBERS:
            raise ValueError("Two through eight ordered member objects required")
        return cls(schema=value["schema"], modal_scope=value["modal_scope"],
                   connective=value["connective"], binding_profile=value["binding_profile"],
                   members=tuple(CoordinationDecodeMember.from_dict(member) for member in members))


def coordination_symbol_registry(labels: tuple[str, ...], slot: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Build stable collision-resistant symbols from semantic labels alone.

    ``source_texts`` is the existing compiler mapping's historical output key;
    its values here are only the supplied semantic labels. This function never
    receives or reads a document, source group, cached target, or provenance.
    """
    if type(slot) is not str or slot not in {"actor", "action"}:
        raise ValueError("Registry slot must be actor or action")
    if type(labels) is not tuple or not 2 <= len(labels) <= MAX_DECODE_MEMBERS:
        raise ValueError("Registry requires two through eight immutable semantic labels")
    entries: dict[str, dict[str, Any]] = {}
    symbols: list[str] = []
    prefix = "Actor" if slot == "actor" else "Action"
    for index, label in enumerate(labels):
        _validate_label(label, actor=slot == "actor")
        identity = semantic_label_identity(label, actor=slot == "actor")
        if identity not in entries:
            readable = re.sub(r"[^A-Za-z0-9]+", "_", identity).strip("_")[:48] or "Source"
            suffix = hashlib.sha256((slot + "\0" + identity).encode("utf-8")).hexdigest()
            entries[identity] = {
                "text": label, "source_texts": [], "symbol": prefix + "_" + readable + "_" + suffix,
                "member_indices": [],
            }
        entry = entries[identity]
        entry["member_indices"].append(index)
        if label not in entry["source_texts"]:
            entry["source_texts"].append(label)
        symbols.append(entry["symbol"])
    return list(entries.values()), symbols


def _normalized_text(request: CoordinationDecodeRequest) -> str:
    names = {"O": "OBLIGATION", "P": "PERMISSION", "F": "PROHIBITION"}

    def label(text: str, *, actor: bool) -> str:
        return json.dumps(semantic_label_identity(text, actor=actor), ensure_ascii=False)

    def binding(member: CoordinationDecodeMember, action: str) -> str:
        return f"for every x, if actor({label(member.actor, actor=True)}, x), then {action}"

    actions = [f"action({label(member.action, actor=False)}, x)" for member in request.members]
    if request.modal_scope == "modal_over_actions":
        first = request.members[0]
        text = names[first.modality] + "[" + binding(first, "(" + " OR ".join(actions) + ")") + "]"
    else:
        clauses = [names[member.modality] + "[" + binding(member, action) + "]"
                   for member, action in zip(request.members, actions)]
        text = "(" + " OR ".join(clauses) + ")"
    return (f"Declared modal scope: {request.modal_scope}; connective: {request.connective}; "
            f"binding: {request.binding_profile}. {text}.")


def render_coordination_request(request: CoordinationDecodeRequest) -> dict[str, Any]:
    """Render validated semantic IR using fixed grammar and native emitters.

    The caller must supply scope and binding choices. Shared-modal scope needs
    identical normalized actors and modal operators. No source recovery, source
    parser, cached teacher artifact, or file is consulted to fill missing slots.
    """
    if type(request) is not CoordinationDecodeRequest:
        raise ValueError("Decoder accepts only a closed typed semantic request")
    request.validate()
    actor_rows, actors = coordination_symbol_registry(tuple(member.actor for member in request.members), "actor")
    action_rows, actions = coordination_symbol_registry(tuple(member.action for member in request.members), "action")
    operators = [member.modality for member in request.members]
    if request.modal_scope == "modal_over_actions":
        if len(set(actors)) != 1 or len(set(operators)) != 1:
            raise ValueError("modal_over_actions requires one normalized actor and modal operator")
        choices = " or ".join(action + "(x)" for action in actions)
        formula = operators[0] + "(forall x. (" + actors[0] + "(x) -> (" + choices + ")))"
    else:
        norms = [operator + "(forall x. (" + actor + "(x) -> " + action + "(x)))"
                 for operator, actor, action in zip(operators, actors, actions)]
        formula = "(" + " or ".join(norms) + ")"
    validation = qualification.validate_family_artifact("deontic_fol", formula)
    if not validation["passed"]:
        raise ValueError("Decoded grouped formula failed strict deontic syntax")
    parsed, _ = qualification._strict_tdfol(formula)
    ast = _ast(parsed)
    payload = {"format": "native_tdfol_ast", "payload": {
        "formulas": [{"source": formula, "ast": ast}],
    }}
    body, native_validation = emitters.native_modal(payload, "tdfol")
    return {
        "schema": COORDINATION_DECODE_RESULT_SCHEMA,
        "context": "source_withheld_semantic_ir", "decoder_kind": "deterministic_ir_renderer",
        "normalized_text": _normalized_text(request), "target_logic": "deontic_fol",
        "formula": formula, "native_ast": ast, "native_payload": payload,
        "mapping": {"actor_symbols": actor_rows, "action_symbols": action_rows},
        "family_validation": validation, "lean_body": body, "native_validation": native_validation,
        "structure_compiled": True, "source_semantics_verified": False,
        "semantic_equivalence_checked": False, "admitted": False, "formalized": False,
        "proof_ready": False, "requires_validation": True,
        "blockers": ["source_interpretation_unreviewed"],
    }


def decode_coordination_request(request: CoordinationDecodeRequest) -> dict[str, Any]:
    """Decode a source-withheld semantic request; never accept source groups."""
    return render_coordination_request(request)
