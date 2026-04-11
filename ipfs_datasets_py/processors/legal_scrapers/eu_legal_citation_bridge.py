"""EU and member-state legal citation normalization and reasoning helpers.

This module is intentionally pragmatic. It does not try to replace a full
jurisdiction-specific citation parser; instead it provides a stable bridge from
official EU/member-state identifiers into:

- multilingual canonical terms
- F-logic frame facts
- deontic temporal first-order logic strings
- deontic cognitive event calculus strings
- a reusable deontic graph
- a lightweight knowledge-graph payload

The first version focuses on official identifiers that travel well across
languages and systems:

- CELEX
- ELI
- ECLI
- Dutch BWB/BWBR identifiers
- Dutch Civil Code article references such as ``Artikel 6:162 BW``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
import inspect

from ipfs_datasets_py.logic.deontic.graph import (
    DeonticGraph,
    DeonticModality,
    DeonticNode,
    DeonticNodeType,
    DeonticRule,
)
from ipfs_datasets_py.logic.flogic.semantic_normalizer import SemanticNormalizer


_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CELEX_RE = re.compile(r"\b(?:CELEX[:\s]*)?(?P<value>[0-9][0-9A-Z]{4}[A-Z0-9()]{2,})\b")
_ECLI_RE = re.compile(r"\b(?P<value>ECLI:[A-Z]{2}:[A-Za-z0-9.]+:[0-9]{4}:[A-Za-z0-9.]+)\b")
_ELI_URL_RE = re.compile(r"\b(?P<value>https?://[^\s)]+/eli/[^\s)]+)\b", re.IGNORECASE)
_BWB_RE = re.compile(r"\b(?P<value>BWBR[0-9A-Z]+)\b", re.IGNORECASE)
_DUTCH_BW_ARTICLE_RE = re.compile(
    r"\b(?:artikel|art\.?)\s+(?P<article>[0-9]+(?::[0-9]+)?[a-z]?)\s+(?P<code>BW)\b",
    re.IGNORECASE,
)
_GERMAN_GG_ARTICLE_RE = re.compile(
    r"\b(?:artikel|art\.?)\s+(?P<article>[0-9]+[a-z]?)\s+(?P<code>GG)\b",
    re.IGNORECASE,
)
_FRENCH_CC_ARTICLE_RE = re.compile(
    r"\b(?:article|art\.?)\s+(?P<article>[0-9]+(?:-[0-9]+)?)\s+du\s+(?P<code>code civil)\b",
    re.IGNORECASE,
)
_SPANISH_CC_ARTICLE_RE = re.compile(
    r"\b(?:art[ií]culo|art\.?)\s+(?P<article>[0-9]+)\s+del\s+(?P<code>c[oó]digo civil)\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.;:])\s+|\n+")


EU_MULTILINGUAL_LEGAL_SYNONYMS: Dict[str, str] = {
    "member state": "member_state",
    "member states": "member_state",
    "lidstaat": "member_state",
    "lidstaten": "member_state",
    "etat membre": "member_state",
    "etats membres": "member_state",
    "mitgliedstaat": "member_state",
    "mitgliedstaaten": "member_state",
    "estado miembro": "member_state",
    "estados miembros": "member_state",
    "estado-membro": "member_state",
    "estados-membros": "member_state",
    "court": "court",
    "rechter": "court",
    "rechtbank": "court",
    "gerechtshof": "court",
    "tribunal": "court",
    "gericht": "court",
    "autoriteit": "authority",
    "authority": "authority",
    "autorite": "authority",
    "behorde": "authority",
    "muss": "required",
    "must": "required",
    "shall": "required",
    "moet": "required",
    "dient": "required",
    "doit": "required",
    "debe": "required",
    "deve": "required",
    "may": "allowed",
    "mag": "allowed",
    "peut": "allowed",
    "puede": "allowed",
    "pode": "allowed",
    "prohibited": "forbidden",
    "forbidden": "forbidden",
    "verboden": "forbidden",
    "interdit": "forbidden",
    "verboten": "forbidden",
    "prohibido": "forbidden",
    "proibido": "forbidden",
}

_DEONTIC_KEYWORDS: Dict[str, Sequence[str]] = {
    "obligation": ("must", "shall", "required", "moet", "dient", "doit", "muss", "debe", "deve"),
    "permission": ("may", "allowed", "mag", "peut", "darf", "puede", "pode"),
    "prohibition": ("forbidden", "prohibited", "shall not", "must not", "verboden", "interdit", "verboten", "prohibido", "proibido"),
}


@dataclass(frozen=True)
class EUJurisdictionProfile:
    code: str
    label: str
    languages: List[str] = field(default_factory=list)
    identifier_schemes: List[str] = field(default_factory=list)
    multilingual_synonyms: Dict[str, str] = field(default_factory=dict)
    modality_keywords: Dict[str, List[str]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EULegalIdentifier:
    scheme: str
    value: str
    jurisdiction: str
    canonical_uri: str
    language: Optional[str] = None
    member_state: Optional[str] = None


@dataclass(frozen=True)
class EULegalCitation:
    raw_text: str
    normalized_text: str
    scheme: str
    citation_type: str
    jurisdiction: str
    canonical_uri: str
    language: Optional[str] = None
    member_state: Optional[str] = None
    identifiers: List[EULegalIdentifier] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EULegalNorm:
    id: str
    modality: str
    actor_text: str
    actor_canonical: str
    action_text: str
    action_canonical: str
    sentence_text: str
    authority_refs: List[str] = field(default_factory=list)
    language: Optional[str] = None
    temporal_scope: Optional[str] = None


@dataclass(frozen=True)
class EULegalReasoningBundle:
    input_text: str
    citations: List[EULegalCitation] = field(default_factory=list)
    jurisdiction_profiles: List[Dict[str, Any]] = field(default_factory=list)
    multilingual_normalization: Dict[str, str] = field(default_factory=dict)
    frame_logic_facts: List[str] = field(default_factory=list)
    temporal_deontic_fol: List[str] = field(default_factory=list)
    deontic_cognitive_event_calculus: List[str] = field(default_factory=list)
    norms: List[EULegalNorm] = field(default_factory=list)
    deontic_graph: Dict[str, Any] = field(default_factory=dict)
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EULegalCitationLookupAction:
    citation: EULegalCitation
    dataset_id: str
    handler_key: str
    query_text: str
    action_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EULegalCitationLookupPlan:
    input_text: str
    actions: List[EULegalCitationLookupAction] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EULegalCitationLookupResult:
    input_text: str
    actions: List[EULegalCitationLookupAction] = field(default_factory=list)
    executed_actions: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


EU_JURISDICTION_PROFILES: Dict[str, EUJurisdictionProfile] = {
    "EU": EUJurisdictionProfile(
        code="EU",
        label="European Union",
        languages=["en", "fr", "de", "es", "nl"],
        identifier_schemes=["CELEX", "ELI", "ECLI"],
        multilingual_synonyms={
            "regulation": "regulation",
            "richtlijn": "directive",
            "directive": "directive",
            "verordnung": "regulation",
            "reglamento": "regulation",
        },
        modality_keywords={key: list(values) for key, values in _DEONTIC_KEYWORDS.items()},
        notes=["Use CELEX and ELI as the primary multilingual statutory anchors."],
    ),
    "NL": EUJurisdictionProfile(
        code="NL",
        label="Netherlands",
        languages=["nl", "en"],
        identifier_schemes=["ECLI", "BWB", "NL_BW_ARTICLE", "ELI"],
        multilingual_synonyms={
            "lidstaat": "member_state",
            "rechtbank": "court",
            "gerechtshof": "court",
            "moet": "required",
            "mag": "allowed",
            "verboden": "forbidden",
        },
        modality_keywords={
            "obligation": ["moet", "dient"],
            "permission": ["mag"],
            "prohibition": ["verboden", "mag niet"],
        },
        notes=["Dutch legislation is best anchored through BWBR/BWB identifiers and artikelen in the BW."],
    ),
    "DE": EUJurisdictionProfile(
        code="DE",
        label="Germany",
        languages=["de", "en"],
        identifier_schemes=["ECLI", "DE_GG_ARTICLE", "ELI"],
        multilingual_synonyms={
            "mitgliedstaat": "member_state",
            "gericht": "court",
            "behörde": "authority",
            "muss": "required",
            "darf": "allowed",
            "verboten": "forbidden",
        },
        modality_keywords={
            "obligation": ["muss", "soll"],
            "permission": ["darf"],
            "prohibition": ["verboten", "darf nicht"],
        },
        notes=["The first German profile focuses on GG article references plus ECLI."],
    ),
    "FR": EUJurisdictionProfile(
        code="FR",
        label="France",
        languages=["fr", "en"],
        identifier_schemes=["ECLI", "FR_CC_ARTICLE", "ELI"],
        multilingual_synonyms={
            "etat membre": "member_state",
            "tribunal": "court",
            "autorité": "authority",
            "doit": "required",
            "peut": "allowed",
            "interdit": "forbidden",
        },
        modality_keywords={
            "obligation": ["doit"],
            "permission": ["peut"],
            "prohibition": ["interdit", "ne peut pas"],
        },
        notes=["The first French profile focuses on Code civil article references plus ECLI."],
    ),
    "ES": EUJurisdictionProfile(
        code="ES",
        label="Spain",
        languages=["es", "en"],
        identifier_schemes=["ECLI", "ES_CC_ARTICLE", "ELI"],
        multilingual_synonyms={
            "estado miembro": "member_state",
            "tribunal": "court",
            "autoridad": "authority",
            "debe": "required",
            "puede": "allowed",
            "prohibido": "forbidden",
        },
        modality_keywords={
            "obligation": ["debe"],
            "permission": ["puede"],
            "prohibition": ["prohibido", "no puede"],
        },
        notes=["The first Spanish profile focuses on Código Civil article references plus ECLI."],
    ),
}


def get_eu_jurisdiction_profiles() -> Dict[str, Dict[str, Any]]:
    return {code: asdict(profile) for code, profile in EU_JURISDICTION_PROFILES.items()}


def _profiles_for_citations(citations: Sequence[EULegalCitation]) -> List[EUJurisdictionProfile]:
    codes = {"EU"}
    for citation in citations:
        if citation.member_state and citation.member_state in EU_JURISDICTION_PROFILES:
            codes.add(citation.member_state)
        elif citation.jurisdiction in EU_JURISDICTION_PROFILES:
            codes.add(citation.jurisdiction)
    return [EU_JURISDICTION_PROFILES[code] for code in sorted(codes) if code in EU_JURISDICTION_PROFILES]


def build_eu_legal_citation_lookup_plan(
    text: str,
    *,
    language: Optional[str] = None,
) -> EULegalCitationLookupPlan:
    citations = extract_eu_legal_citations(text, language=language)
    actions: List[EULegalCitationLookupAction] = []
    notes: List[str] = []
    for citation in citations:
        handler_key = "eu_registry"
        dataset_id = "eu_legal_registry"
        action_type = "registry_lookup"
        query_text = citation.canonical_uri
        action_notes: List[str] = []

        if citation.scheme in {"CELEX", "ELI"}:
            handler_key = "eurlex_registry"
            dataset_id = "eurlex"
            action_type = "eu_legislation_lookup"
            query_text = citation.canonical_uri
            action_notes.append("Prefer EUR-Lex/Eli resolvers for CELEX/ELI anchors.")
        elif citation.scheme == "ECLI":
            handler_key = "ecli_registry"
            dataset_id = "ecli"
            action_type = "case_law_lookup"
            query_text = citation.normalized_text
            action_notes.append("Prefer ECLI resolvers for case law anchors.")
        elif citation.member_state == "NL":
            handler_key = "netherlands_laws"
            dataset_id = "netherlands_laws"
            action_type = "member_state_law_lookup"
            query_text = citation.normalized_text
            action_notes.append("Use Netherlands law corpus search for BWBR/BW references.")
        elif citation.member_state in {"DE", "FR", "ES"}:
            handler_key = f"{citation.member_state.lower()}_law_registry"
            dataset_id = f"{citation.member_state.lower()}_law_registry"
            action_type = "member_state_law_lookup"
            query_text = citation.normalized_text
            action_notes.append("Provide a member-state handler to execute this lookup.")
        else:
            action_notes.append("Provide a custom handler to resolve this citation.")

        actions.append(
            EULegalCitationLookupAction(
                citation=citation,
                dataset_id=dataset_id,
                handler_key=handler_key,
                query_text=query_text,
                action_type=action_type,
                parameters={"language": language, "member_state": citation.member_state},
                notes=action_notes,
            )
        )

    if not actions:
        notes.append("No EU/member-state identifiers detected in input.")
    return EULegalCitationLookupPlan(
        input_text=str(text or ""),
        actions=actions,
        notes=notes,
    )


async def execute_eu_legal_citation_lookup_plan(
    plan: EULegalCitationLookupPlan,
    *,
    lookup_handlers: Optional[Dict[str, Callable[[EULegalCitationLookupAction], Any]]] = None,
) -> EULegalCitationLookupResult:
    handlers = dict(lookup_handlers or {})
    executed_actions: List[Dict[str, Any]] = []

    for action in plan.actions:
        handler = handlers.get(action.handler_key)
        if handler is None:
            executed_actions.append(
                {
                    "handler_key": action.handler_key,
                    "dataset_id": action.dataset_id,
                    "query_text": action.query_text,
                    "executed": False,
                    "results": [],
                    "notes": ["No handler registered for this lookup key."],
                }
            )
            continue
        result = handler(action)
        if inspect.isawaitable(result):
            result = await result
        executed_actions.append(
            {
                "handler_key": action.handler_key,
                "dataset_id": action.dataset_id,
                "query_text": action.query_text,
                "executed": True,
                "results": result,
                "notes": list(action.notes),
            }
        )

    return EULegalCitationLookupResult(
        input_text=plan.input_text,
        actions=list(plan.actions),
        executed_actions=executed_actions,
        notes=list(plan.notes),
    )


def eu_legal_citation_lookup_plan_to_dict(plan: EULegalCitationLookupPlan) -> Dict[str, Any]:
    return {
        "input_text": plan.input_text,
        "actions": [
            {
                "citation": asdict(action.citation),
                "dataset_id": action.dataset_id,
                "handler_key": action.handler_key,
                "query_text": action.query_text,
                "action_type": action.action_type,
                "parameters": dict(action.parameters),
                "notes": list(action.notes),
            }
            for action in plan.actions
        ],
        "notes": list(plan.notes),
    }


def eu_legal_citation_lookup_result_to_dict(result: EULegalCitationLookupResult) -> Dict[str, Any]:
    return {
        "input_text": result.input_text,
        "actions": [
            {
                "citation": asdict(action.citation),
                "dataset_id": action.dataset_id,
                "handler_key": action.handler_key,
                "query_text": action.query_text,
                "action_type": action.action_type,
                "parameters": dict(action.parameters),
                "notes": list(action.notes),
            }
            for action in result.actions
        ],
        "executed_actions": list(result.executed_actions),
        "notes": list(result.notes),
    }


def build_default_eu_lookup_handlers(
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Callable[[EULegalCitationLookupAction], Any]]:
    def _noop_handler(action: EULegalCitationLookupAction) -> Dict[str, Any]:
        return {
            "resolved": False,
            "query": action.query_text,
            "results": [],
            "notes": ["No built-in resolver is registered for this handler key."],
        }

    async def _netherlands_handler(action: EULegalCitationLookupAction) -> Dict[str, Any]:
        try:
            from .legal_dataset_api import search_netherlands_law_corpus_from_parameters
        except Exception:
            return {
                "resolved": False,
                "query": action.query_text,
                "results": [],
                "notes": ["Netherlands law search backend not available."],
            }
        params = {
            "query_text": action.query_text,
            "citation_query": action.query_text,
            "language": action.parameters.get("language"),
            "member_state": action.parameters.get("member_state"),
        }
        return await search_netherlands_law_corpus_from_parameters(params, tool_version=tool_version)

    return {
        "eurlex_registry": _noop_handler,
        "ecli_registry": _noop_handler,
        "eu_registry": _noop_handler,
        "netherlands_laws": _netherlands_handler,
    }


def _normalize_space(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _slug(value: Any) -> str:
    compact = _NON_ALNUM_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return compact or "unknown"


def _canonicalize_eu_identifier(
    scheme: str,
    value: str,
    *,
    language: Optional[str] = None,
    member_state: Optional[str] = None,
) -> EULegalIdentifier:
    normalized_value = _normalize_space(value)
    scheme_upper = str(scheme or "").upper()
    if scheme_upper == "CELEX":
        canonical_uri = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{normalized_value}"
        jurisdiction = "EU"
    elif scheme_upper == "ELI":
        canonical_uri = normalized_value if normalized_value.startswith("http") else f"eli:{normalized_value}"
        jurisdiction = "EU"
    elif scheme_upper == "ECLI":
        canonical_uri = f"ecli:{normalized_value}"
        jurisdiction = member_state or "EU"
    elif scheme_upper == "BWB":
        canonical_uri = f"https://wetten.overheid.nl/{normalized_value}/"
        jurisdiction = "NL"
        member_state = "NL"
    elif scheme_upper == "NL_BW_ARTICLE":
        canonical_uri = f"https://wetten.overheid.nl/jci1.3:c:BWBR0005289&artikel={normalized_value}"
        jurisdiction = "NL"
        member_state = "NL"
    elif scheme_upper == "DE_GG_ARTICLE":
        canonical_uri = f"https://www.gesetze-im-internet.de/gg/art_{normalized_value.split()[0]}.html"
        jurisdiction = "DE"
        member_state = "DE"
    elif scheme_upper == "FR_CC_ARTICLE":
        canonical_uri = f"https://www.legifrance.gouv.fr/codes/article_lc/{_slug(normalized_value)}"
        jurisdiction = "FR"
        member_state = "FR"
    elif scheme_upper == "ES_CC_ARTICLE":
        canonical_uri = f"https://www.boe.es/buscar/act.php?id=BOE-A-1889-4763#art{normalized_value.split()[0]}"
        jurisdiction = "ES"
        member_state = "ES"
    else:
        canonical_uri = normalized_value
        jurisdiction = member_state or "EU"
    return EULegalIdentifier(
        scheme=scheme_upper,
        value=normalized_value,
        jurisdiction=jurisdiction,
        canonical_uri=canonical_uri,
        language=language,
        member_state=member_state,
    )


def extract_eu_legal_citations(text: str, *, language: Optional[str] = None) -> List[EULegalCitation]:
    content = str(text or "")
    citations: List[EULegalCitation] = []
    seen: set[tuple[str, str]] = set()

    def _append(
        raw_text: str,
        *,
        scheme: str,
        citation_type: str,
        jurisdiction: str,
        member_state: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        normalized_text = _normalize_space(raw_text)
        key = (scheme.upper(), normalized_text)
        if not normalized_text or key in seen:
            return
        seen.add(key)
        identifier = _canonicalize_eu_identifier(
            scheme,
            normalized_text,
            language=language,
            member_state=member_state,
        )
        citations.append(
            EULegalCitation(
                raw_text=raw_text,
                normalized_text=normalized_text,
                scheme=identifier.scheme,
                citation_type=citation_type,
                jurisdiction=jurisdiction,
                canonical_uri=identifier.canonical_uri,
                language=language,
                member_state=member_state,
                identifiers=[identifier],
                metadata=dict(metadata or {}),
            )
        )

    for match in _CELEX_RE.finditer(content):
        _append(match.group("value"), scheme="CELEX", citation_type="eu_legislation", jurisdiction="EU")
    for match in _ELI_URL_RE.finditer(content):
        _append(match.group("value"), scheme="ELI", citation_type="eu_or_member_state_legislation", jurisdiction="EU")
    for match in _ECLI_RE.finditer(content):
        raw = match.group("value")
        parts = raw.split(":")
        member_state = parts[1] if len(parts) > 1 else None
        _append(raw, scheme="ECLI", citation_type="case_law", jurisdiction=member_state or "EU", member_state=member_state)
    for match in _BWB_RE.finditer(content):
        _append(match.group("value").upper(), scheme="BWB", citation_type="member_state_legislation", jurisdiction="NL", member_state="NL")
    for match in _DUTCH_BW_ARTICLE_RE.finditer(content):
        article = match.group("article")
        code = match.group("code").upper()
        _append(
            f"{article} {code}",
            scheme="NL_BW_ARTICLE",
            citation_type="member_state_legislation",
            jurisdiction="NL",
            member_state="NL",
            metadata={"article": article, "code": code},
        )
    for match in _GERMAN_GG_ARTICLE_RE.finditer(content):
        article = match.group("article")
        code = match.group("code").upper()
        _append(
            f"{article} {code}",
            scheme="DE_GG_ARTICLE",
            citation_type="member_state_legislation",
            jurisdiction="DE",
            member_state="DE",
            metadata={"article": article, "code": code},
        )
    for match in _FRENCH_CC_ARTICLE_RE.finditer(content):
        article = match.group("article")
        code = _normalize_space(match.group("code")).lower()
        _append(
            f"{article} {code}",
            scheme="FR_CC_ARTICLE",
            citation_type="member_state_legislation",
            jurisdiction="FR",
            member_state="FR",
            metadata={"article": article, "code": code},
        )
    for match in _SPANISH_CC_ARTICLE_RE.finditer(content):
        article = match.group("article")
        code = _normalize_space(match.group("code")).lower()
        _append(
            f"{article} {code}",
            scheme="ES_CC_ARTICLE",
            citation_type="member_state_legislation",
            jurisdiction="ES",
            member_state="ES",
            metadata={"article": article, "code": code},
        )

    return citations


def build_eu_multilingual_normalization_map(
    terms: Iterable[str],
    *,
    profile_codes: Optional[Sequence[str]] = None,
    extra_synonyms: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    synonym_map = dict(EU_MULTILINGUAL_LEGAL_SYNONYMS)
    for code in list(profile_codes or []):
        profile = EU_JURISDICTION_PROFILES.get(str(code))
        if profile is not None:
            synonym_map.update(profile.multilingual_synonyms)
    synonym_map.update(extra_synonyms or {})
    normalizer = SemanticNormalizer(use_symai=False, synonym_map=synonym_map)
    normalized: Dict[str, str] = {}
    for term in terms:
        token = _normalize_space(term).lower()
        if token:
            normalized[token] = normalizer.normalize_term(token)
    return normalized


def _detect_modality(sentence: str) -> Optional[str]:
    return _detect_modality_with_keywords(sentence, _DEONTIC_KEYWORDS)


def _detect_modality_with_keywords(
    sentence: str,
    keyword_map: Dict[str, Sequence[str]],
) -> Optional[str]:
    lowered = f" {_normalize_space(sentence).lower()} "
    for modality, keywords in keyword_map.items():
        for keyword in keywords:
            if f" {keyword.lower()} " in lowered:
                return modality
    return None


def _first_keyword(modality: str, sentence: str) -> str:
    return _first_keyword_from_map(modality, sentence, _DEONTIC_KEYWORDS)


def _first_keyword_from_map(
    modality: str,
    sentence: str,
    keyword_map: Dict[str, Sequence[str]],
) -> str:
    lowered = sentence.lower()
    candidates = [keyword for keyword in keyword_map.get(modality, ()) if keyword in lowered]
    return sorted(candidates, key=lambda item: lowered.index(item))[0] if candidates else ""


def _canonicalize_phrase(phrase: str, normalizer: SemanticNormalizer) -> str:
    tokens = [normalizer.normalize_term(token) for token in re.findall(r"[A-Za-zÀ-ÿ0-9:_-]+", phrase.lower())]
    return "_".join(token for token in tokens if token) or "unspecified"


def extract_eu_deontic_norms(
    text: str,
    *,
    citations: Optional[Sequence[EULegalCitation]] = None,
    language: Optional[str] = None,
    profile_codes: Optional[Sequence[str]] = None,
    extra_synonyms: Optional[Dict[str, str]] = None,
) -> List[EULegalNorm]:
    synonym_map = dict(EU_MULTILINGUAL_LEGAL_SYNONYMS)
    keyword_map: Dict[str, List[str]] = {key: list(values) for key, values in _DEONTIC_KEYWORDS.items()}
    for code in list(profile_codes or []):
        profile = EU_JURISDICTION_PROFILES.get(str(code))
        if profile is not None:
            synonym_map.update(profile.multilingual_synonyms)
            for modality, values in profile.modality_keywords.items():
                keyword_map.setdefault(modality, [])
                for value in values:
                    if value not in keyword_map[modality]:
                        keyword_map[modality].append(value)
    synonym_map.update(extra_synonyms or {})
    normalizer = SemanticNormalizer(use_symai=False, synonym_map=synonym_map)
    authority_refs = [citation.canonical_uri for citation in list(citations or [])]

    norms: List[EULegalNorm] = []
    for index, sentence in enumerate(_SENTENCE_RE.split(str(text or "")), start=1):
        clean = _normalize_space(sentence)
        if not clean:
            continue
        modality = _detect_modality_with_keywords(clean, keyword_map)
        if modality is None:
            continue
        keyword = _first_keyword_from_map(modality, clean, keyword_map)
        parts = re.split(re.escape(keyword), clean, maxsplit=1, flags=re.IGNORECASE) if keyword else [clean]
        actor_text = _normalize_space(parts[0]) or "unspecified_actor"
        action_text = _normalize_space(parts[1]) if len(parts) > 1 else clean
        norms.append(
            EULegalNorm(
                id=f"eu_norm_{index}",
                modality=modality,
                actor_text=actor_text,
                actor_canonical=_canonicalize_phrase(actor_text, normalizer),
                action_text=action_text,
                action_canonical=_canonicalize_phrase(action_text, normalizer),
                sentence_text=clean,
                authority_refs=list(authority_refs),
                language=language,
                temporal_scope="during_document_validity",
            )
        )
    return norms


def build_eu_frame_logic_facts(
    citations: Sequence[EULegalCitation],
    norms: Sequence[EULegalNorm],
) -> List[str]:
    facts: List[str] = []
    for index, citation in enumerate(citations, start=1):
        fact_id = f"eu_doc_{index}"
        facts.append(
            f'{fact_id}[scheme -> "{citation.scheme}"; jurisdiction -> "{citation.jurisdiction}"; canonical_uri -> "{citation.canonical_uri}"].'
        )
        if citation.member_state:
            facts.append(f'{fact_id}[member_state -> "{citation.member_state}"].')
    for norm in norms:
        facts.append(
            f'{norm.id}[modality -> "{norm.modality}"; actor -> "{norm.actor_canonical}"; action -> "{norm.action_canonical}"].'
        )
        for authority_ref in norm.authority_refs:
            facts.append(f'{norm.id}[authority_ref -> "{authority_ref}"].')
    return facts


def build_eu_temporal_deontic_fol(
    norms: Sequence[EULegalNorm],
) -> List[str]:
    formulas: List[str] = []
    for norm in norms:
        operator = {
            "obligation": "O",
            "permission": "P",
            "prohibition": "F",
        }.get(norm.modality, "N")
        formulas.append(
            f'{operator}({norm.actor_canonical}, {norm.action_canonical}, t_document, "{norm.id}")'
        )
    return formulas


def build_eu_deontic_cognitive_event_calculus(
    norms: Sequence[EULegalNorm],
) -> List[str]:
    assertions: List[str] = []
    for norm in norms:
        event = f"norm_event({norm.id})"
        assertions.append(f"Initiates({event}, {norm.modality}({norm.actor_canonical}, {norm.action_canonical}), t_document)")
        assertions.append(f"HoldsAt(authority_basis({norm.id}), t_document)")
    return assertions


def build_eu_deontic_graph(
    citations: Sequence[EULegalCitation],
    norms: Sequence[EULegalNorm],
) -> DeonticGraph:
    graph = DeonticGraph()
    for citation in citations:
        authority_id = f"authority_{_slug(citation.scheme)}_{_slug(citation.normalized_text)}"
        graph.add_node(
            DeonticNode(
                id=authority_id,
                node_type=DeonticNodeType.AUTHORITY,
                label=citation.normalized_text,
                active=True,
                confidence=1.0,
                attributes={
                    "scheme": citation.scheme,
                    "canonical_uri": citation.canonical_uri,
                    "jurisdiction": citation.jurisdiction,
                    "member_state": citation.member_state,
                },
            )
        )
    for norm in norms:
        actor_id = f"actor_{norm.actor_canonical}"
        action_id = f"action_{norm.action_canonical}"
        if graph.get_node(actor_id) is None:
            graph.add_node(
                DeonticNode(
                    id=actor_id,
                    node_type=DeonticNodeType.ACTOR,
                    label=norm.actor_text,
                    active=True,
                    confidence=0.8,
                    attributes={"canonical": norm.actor_canonical},
                )
            )
        if graph.get_node(action_id) is None:
            graph.add_node(
                DeonticNode(
                    id=action_id,
                    node_type=DeonticNodeType.ACTION,
                    label=norm.action_text,
                    active=True,
                    confidence=0.8,
                    attributes={"canonical": norm.action_canonical},
                )
            )
        graph.add_rule(
            DeonticRule(
                id=norm.id,
                modality={
                    "obligation": DeonticModality.OBLIGATION,
                    "permission": DeonticModality.PERMISSION,
                    "prohibition": DeonticModality.PROHIBITION,
                }.get(norm.modality, DeonticModality.ENTITLEMENT),
                source_ids=[actor_id],
                target_id=action_id,
                predicate=norm.action_canonical,
                active=True,
                confidence=0.8,
                authority_ids=[f"authority_{_slug(citation.scheme)}_{_slug(citation.normalized_text)}" for citation in citations],
                evidence_ids=[citation.canonical_uri for citation in citations],
                attributes={
                    "sentence_text": norm.sentence_text,
                    "language": norm.language,
                    "temporal_scope": norm.temporal_scope,
                },
            )
        )
    return graph


def build_eu_knowledge_graph(
    citations: Sequence[EULegalCitation],
    norms: Sequence[EULegalNorm],
) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for citation in citations:
        node_id = f"citation_{_slug(citation.scheme)}_{_slug(citation.normalized_text)}"
        nodes.append(
            {
                "id": node_id,
                "type": "authority",
                "label": citation.normalized_text,
                "canonical_uri": citation.canonical_uri,
                "scheme": citation.scheme,
                "jurisdiction": citation.jurisdiction,
                "member_state": citation.member_state,
            }
        )
    for norm in norms:
        norm_node_id = norm.id
        actor_node_id = f"actor_{norm.actor_canonical}"
        action_node_id = f"action_{norm.action_canonical}"
        nodes.extend(
            [
                {"id": norm_node_id, "type": "norm", "label": norm.sentence_text, "modality": norm.modality},
                {"id": actor_node_id, "type": "actor", "label": norm.actor_text, "canonical": norm.actor_canonical},
                {"id": action_node_id, "type": "action", "label": norm.action_text, "canonical": norm.action_canonical},
            ]
        )
        edges.extend(
            [
                {"source": actor_node_id, "target": norm_node_id, "predicate": "governed_by"},
                {"source": norm_node_id, "target": action_node_id, "predicate": norm.modality},
            ]
        )
        for citation in citations:
            citation_node_id = f"citation_{_slug(citation.scheme)}_{_slug(citation.normalized_text)}"
            edges.append({"source": citation_node_id, "target": norm_node_id, "predicate": "authorizes"})
    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "citation_count": len(citations),
            "norm_count": len(norms),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }


def build_eu_legal_reasoning_bundle(
    text: str,
    *,
    language: Optional[str] = None,
    extra_synonyms: Optional[Dict[str, str]] = None,
) -> EULegalReasoningBundle:
    citations = extract_eu_legal_citations(text, language=language)
    active_profiles = _profiles_for_citations(citations)
    active_profile_codes = [profile.code for profile in active_profiles]
    raw_terms: List[str] = []
    for citation in citations:
        raw_terms.append(citation.scheme)
        if citation.member_state:
            raw_terms.append(citation.member_state)
    raw_terms.extend(re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ_-]+", str(text or "")))
    multilingual_map = build_eu_multilingual_normalization_map(
        raw_terms,
        profile_codes=active_profile_codes,
        extra_synonyms=extra_synonyms,
    )
    norms = extract_eu_deontic_norms(
        text,
        citations=citations,
        language=language,
        profile_codes=active_profile_codes,
        extra_synonyms=extra_synonyms,
    )
    frame_logic_facts = build_eu_frame_logic_facts(citations, norms)
    temporal_deontic_fol = build_eu_temporal_deontic_fol(norms)
    cec_assertions = build_eu_deontic_cognitive_event_calculus(norms)
    deontic_graph = build_eu_deontic_graph(citations, norms)
    knowledge_graph = build_eu_knowledge_graph(citations, norms)

    notes = [
        "Use CELEX, ELI, ECLI, and member-state official identifiers as the multilingual anchor layer.",
        "Semantic normalization is dictionary-driven in this first version so behavior stays deterministic and testable.",
        "The generated F-logic, temporal-deontic, and CEC outputs are bridge artifacts intended for downstream provers and graph pipelines.",
    ]
    return EULegalReasoningBundle(
        input_text=str(text or ""),
        citations=citations,
        jurisdiction_profiles=[asdict(profile) for profile in active_profiles],
        multilingual_normalization=multilingual_map,
        frame_logic_facts=frame_logic_facts,
        temporal_deontic_fol=temporal_deontic_fol,
        deontic_cognitive_event_calculus=cec_assertions,
        norms=norms,
        deontic_graph={
            "nodes": [node.to_dict() for node in deontic_graph.nodes.values()],
            "rules": [rule.to_dict() for rule in deontic_graph.rules.values()],
            "summary": deontic_graph.summary(),
            "assessments": [item.to_dict() for item in deontic_graph.assess_rules()],
        },
        knowledge_graph=knowledge_graph,
        notes=notes,
    )


def eu_legal_reasoning_bundle_to_dict(bundle: EULegalReasoningBundle) -> Dict[str, Any]:
    return {
        "input_text": bundle.input_text,
        "citations": [
            {
                **asdict(citation),
                "identifiers": [asdict(identifier) for identifier in citation.identifiers],
            }
            for citation in bundle.citations
        ],
        "jurisdiction_profiles": [dict(profile) for profile in bundle.jurisdiction_profiles],
        "multilingual_normalization": dict(bundle.multilingual_normalization),
        "frame_logic_facts": list(bundle.frame_logic_facts),
        "temporal_deontic_fol": list(bundle.temporal_deontic_fol),
        "deontic_cognitive_event_calculus": list(bundle.deontic_cognitive_event_calculus),
        "norms": [asdict(norm) for norm in bundle.norms],
        "deontic_graph": dict(bundle.deontic_graph),
        "knowledge_graph": dict(bundle.knowledge_graph),
        "notes": list(bundle.notes),
    }
