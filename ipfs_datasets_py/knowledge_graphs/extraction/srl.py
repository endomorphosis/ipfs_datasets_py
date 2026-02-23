"""
Semantic Role Labeling (SRL) Module.

This module implements event-centric knowledge graph extraction via Semantic
Role Labeling (SRL) — previously Item 9 in DEFERRED_FEATURES.md.

The extractor identifies **predicate–argument structures** in text and maps
each argument to a canonical semantic role:

    Agent       — the entity performing the action  (``nsubj``, active voice)
    Patient     — the entity being acted upon        (``dobj``, ``nsubjpass``)
    Theme       — inanimate thing involved           (heuristic if not patient)
    Instrument  — tool/means used                   ("with …", "using …")
    Location    — spatial modifier                  ("in …", "at …", "from …")
    Time        — temporal modifier                 ("on …", "after …", "when …")
    Cause       — causal modifier                   ("because …", "due to …")
    Result      — result of the action              ("so that …", "resulting in …")

Each predicate produces one :class:`SRLFrame`; frames can be written into a
:class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
as event-centric nodes (one ``Event`` entity per frame, connected to role
entities via typed relationships such as ``hasAgent``, ``hasPatient``, …).

Two execution modes are supported, selected transparently at runtime:

* **spaCy mode** (preferred) — accurate, uses the loaded ``nlp`` model's
  dependency parse to locate verbs and their syntactic arguments.
* **Heuristic mode** (fallback) — regex + simple POS heuristics; works
  without any third-party models.

Usage::

    from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

    extractor = SRLExtractor()          # heuristic by default
    frames = extractor.extract_srl("Alice sent the report to Bob yesterday.")
    kg = extractor.to_knowledge_graph(frames)

    # with spaCy (if available)
    extractor_spacy = SRLExtractor(nlp=spacy_model)
    frames = extractor_spacy.extract_srl(text)
"""

from __future__ import annotations

import re
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Semantic role constants
# ---------------------------------------------------------------------------

ROLE_AGENT = "Agent"
ROLE_PATIENT = "Patient"
ROLE_THEME = "Theme"
ROLE_INSTRUMENT = "Instrument"
ROLE_LOCATION = "Location"
ROLE_TIME = "Time"
ROLE_CAUSE = "Cause"
ROLE_RESULT = "Result"
ROLE_RECIPIENT = "Recipient"
ROLE_SOURCE = "Source"

# Relationships emitted into the KG for each role
_ROLE_TO_RELATIONSHIP: Dict[str, str] = {
    ROLE_AGENT: "hasAgent",
    ROLE_PATIENT: "hasPatient",
    ROLE_THEME: "hasTheme",
    ROLE_INSTRUMENT: "hasInstrument",
    ROLE_LOCATION: "hasLocation",
    ROLE_TIME: "hasTime",
    ROLE_CAUSE: "hasCause",
    ROLE_RESULT: "hasResult",
    ROLE_RECIPIENT: "hasRecipient",
    ROLE_SOURCE: "hasSource",
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RoleArgument:
    """A single role–argument binding within an :class:`SRLFrame`.

    Attributes:
        role:   Semantic role label (e.g. ``"Agent"``, ``"Patient"``).
        text:   Surface-form text of the argument span.
        span:   ``(start, end)`` character offsets in the original sentence,
                or ``None`` if not determinable.
        confidence: Extraction confidence in *[0, 1]*.
    """

    role: str
    text: str
    span: Optional[Tuple[int, int]] = None
    confidence: float = 0.8


@dataclass
class SRLFrame:
    """Represents the predicate–argument structure of a single predicate.

    Attributes:
        frame_id:   Unique identifier.
        predicate:  Surface form of the predicate verb (lemma when available).
        predicate_span: ``(start, end)`` character offsets of the predicate.
        sentence:   Full sentence text.
        arguments:  List of :class:`RoleArgument` objects.
        confidence: Overall confidence score for this frame.
        source:     ``"spacy"`` or ``"heuristic"``.
    """

    frame_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    predicate: str = ""
    predicate_span: Optional[Tuple[int, int]] = None
    sentence: str = ""
    arguments: List[RoleArgument] = field(default_factory=list)
    confidence: float = 0.7
    source: str = "heuristic"

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_role(self, role: str) -> Optional[RoleArgument]:
        """Return the first argument with the given *role*, or ``None``."""
        for arg in self.arguments:
            if arg.role == role:
                return arg
        return None

    def get_roles(self, role: str) -> List[RoleArgument]:
        """Return all arguments with the given *role*."""
        return [a for a in self.arguments if a.role == role]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "frame_id": self.frame_id,
            "predicate": self.predicate,
            "predicate_span": list(self.predicate_span) if self.predicate_span else None,
            "sentence": self.sentence,
            "arguments": [
                {
                    "role": a.role,
                    "text": a.text,
                    "span": list(a.span) if a.span else None,
                    "confidence": a.confidence,
                }
                for a in self.arguments
            ],
            "confidence": self.confidence,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SRLFrame":
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary with the same keys as :meth:`to_dict`.

        Returns:
            New :class:`SRLFrame` populated from *data*.
        """
        args = [
            RoleArgument(
                role=a["role"],
                text=a["text"],
                span=tuple(a["span"]) if a.get("span") else None,  # type: ignore[arg-type]
                confidence=a.get("confidence", 0.8),
            )
            for a in data.get("arguments", [])
        ]
        ps = data.get("predicate_span")
        return cls(
            frame_id=data.get("frame_id", str(uuid.uuid4())),
            predicate=data.get("predicate", ""),
            predicate_span=tuple(ps) if ps else None,  # type: ignore[arg-type]
            sentence=data.get("sentence", ""),
            arguments=args,
            confidence=data.get("confidence", 0.7),
            source=data.get("source", "heuristic"),
        )


# ---------------------------------------------------------------------------
# Heuristic helpers (no external dependencies)
# ---------------------------------------------------------------------------

# Simple patterns for modifier detection
_INSTRUMENT_RE = re.compile(
    r"\b(?:with|using|by means of|via|through)\s+([\w\s]+?)(?:[,;]|$)", re.I
)
_LOCATION_RE = re.compile(
    r"\b(?:in|at|on|from|to|into|near|towards?)\s+([\w\s]+?)(?:[,;]|$)", re.I
)
_TIME_RE = re.compile(
    r"\b(?:on|at|in|after|before|during|when|while|since|until|yesterday|today|"
    r"tomorrow|now|then|later|earlier|(?:last|next|this)\s+\w+)\s*([\w\s]*?)(?:[,;]|$)",
    re.I,
)
_CAUSE_RE = re.compile(
    r"\b(?:because|since|as|due to|owing to|given that|for)\s+([\w\s]+?)(?:[,;]|$)",
    re.I,
)
_RESULT_RE = re.compile(
    r"\b(?:so that|so|resulting in|leading to|consequently|therefore)\s+([\w\s]+?)(?:[,;]|$)",
    re.I,
)
_RECIPIENT_RE = re.compile(
    r"\b(?:to|for|towards?)\s+([\w]+)(?:[,;\s]|$)", re.I
)

# Common auxiliary / copula verbs to skip
_AUX_VERBS = frozenset(
    "am is are was were be been being have has had do does did will would could "
    "should may might shall must can".split()
)

# Very rough English verb detection: ends in common verb suffixes or is in a
# core verb list.
_CORE_VERBS = frozenset(
    "say says said tell tells told give gives gave take takes took make makes made "
    "know knows knew think thinks thought see sees saw look looks looked use uses used "
    "find finds found want wants wanted need needs needed get gets got come comes came "
    "go goes went show shows showed work works worked include includes included "
    "provide provides provided send sends sent receive receives received report reports "
    "reported create creates created build builds built develop develops developed "
    "release releases released announce announces announced launch launches launched "
    "acquire acquires acquired merge merges merged buy buys bought sell sells sold "
    "hire hires hired fire fires fired join joins joined leave leaves left found "
    "founded publish publishes published write writes wrote research researches "
    "researched study studies studied analyze analyzes analyzed".split()
)


def _looks_like_verb(token: str) -> bool:
    t = token.lower().rstrip("s")
    return (
        t in _CORE_VERBS
        or token.lower().endswith("ed")
        or token.lower().endswith("ing")
    ) and token.lower() not in _AUX_VERBS


def _extract_heuristic_frames(sentence: str) -> List[SRLFrame]:
    """Extract SRL frames using simple heuristic rules (no spaCy required)."""
    frames: List[SRLFrame] = []
    words = sentence.split()
    if not words:
        return frames

    # Find verb candidates
    for i, word in enumerate(words):
        clean = re.sub(r"[^a-zA-Z]", "", word)
        if not clean or not _looks_like_verb(clean):
            continue

        # Candidate predicate at position i
        # Agent heuristic: first proper-noun-like or capitalized word before verb
        agent_text: Optional[str] = None
        patient_text: Optional[str] = None

        # Words before the verb — pick the last non-auxiliary, non-preposition group
        pre_words = [w for w in words[:i] if w.lower() not in _AUX_VERBS]
        if pre_words:
            # Strip punctuation from each pre-word
            agent_text = " ".join(
                re.sub(r"[^a-zA-Z0-9\-_']", "", w) for w in pre_words[-2:]
            ).strip() or None

        # Words after the verb — simple object detection
        post_words = words[i + 1:]
        # Stop at common prepositions / connectors to get the direct object
        obj_words: List[str] = []
        for w in post_words:
            if w.lower() in ("in", "at", "on", "from", "to", "with", "by", "for",
                             "because", "since", "after", "before", "when", "while",
                             "and", "or", "but", "so", "that", "which", "who"):
                break
            obj_words.append(re.sub(r"[,;.]", "", w))
        if obj_words:
            patient_text = " ".join(obj_words).strip() or None

        if not agent_text and not patient_text:
            continue

        arguments: List[RoleArgument] = []
        if agent_text:
            arguments.append(RoleArgument(role=ROLE_AGENT, text=agent_text, confidence=0.65))
        if patient_text:
            role = ROLE_PATIENT if agent_text else ROLE_THEME
            arguments.append(RoleArgument(role=role, text=patient_text, confidence=0.65))

        # Modifier scanning over the full sentence
        for m in _INSTRUMENT_RE.finditer(sentence):
            span_text = m.group(1).strip()
            if span_text:
                arguments.append(RoleArgument(
                    role=ROLE_INSTRUMENT, text=span_text,
                    span=(m.start(1), m.end(1)), confidence=0.6,
                ))

        for m in _LOCATION_RE.finditer(sentence):
            span_text = m.group(1).strip()
            if span_text:
                arguments.append(RoleArgument(
                    role=ROLE_LOCATION, text=span_text,
                    span=(m.start(1), m.end(1)), confidence=0.55,
                ))

        for m in _TIME_RE.finditer(sentence):
            span_text = (m.group(1) or "").strip()
            if span_text:
                arguments.append(RoleArgument(
                    role=ROLE_TIME, text=span_text,
                    span=(m.start(1), m.end(1)), confidence=0.55,
                ))

        for m in _CAUSE_RE.finditer(sentence):
            span_text = m.group(1).strip()
            if span_text:
                arguments.append(RoleArgument(
                    role=ROLE_CAUSE, text=span_text,
                    span=(m.start(1), m.end(1)), confidence=0.6,
                ))

        for m in _RESULT_RE.finditer(sentence):
            span_text = m.group(1).strip()
            if span_text:
                arguments.append(RoleArgument(
                    role=ROLE_RESULT, text=span_text,
                    span=(m.start(1), m.end(1)), confidence=0.6,
                ))

        frames.append(SRLFrame(
            predicate=clean,
            sentence=sentence,
            arguments=arguments,
            confidence=0.65,
            source="heuristic",
        ))
        break  # one frame per sentence for heuristic mode (main verb only)

    return frames


# ---------------------------------------------------------------------------
# spaCy-based extraction
# ---------------------------------------------------------------------------

def _extract_spacy_frames(sentence_span: Any) -> List[SRLFrame]:
    """Extract SRL frames from a spaCy *sentence span*."""
    frames: List[SRLFrame] = []
    sent_text = sentence_span.text

    for token in sentence_span:
        if token.pos_ not in ("VERB", "AUX"):
            continue
        if token.lemma_.lower() in _AUX_VERBS:
            continue

        arguments: List[RoleArgument] = []

        for child in token.children:
            dep = child.dep_.lower()
            span_text = child.text.strip()
            if not span_text:
                continue

            if dep in ("nsubj", "nsubjpass", "agent", "expl"):
                role = ROLE_AGENT
            elif dep in ("dobj", "obj", "iobj", "pobj", "attr"):
                role = ROLE_PATIENT
            elif dep == "dative":
                role = ROLE_RECIPIENT
            elif dep in ("prep", "advmod", "npadvmod"):
                # Further classify by the prep text
                prep_text = child.text.lower()
                if prep_text in ("with", "using", "by", "via", "through"):
                    role = ROLE_INSTRUMENT
                elif prep_text in ("in", "at", "on", "near", "from", "to",
                                   "into", "toward", "towards"):
                    role = ROLE_LOCATION
                elif prep_text in ("when", "before", "after", "during",
                                   "since", "until", "while"):
                    role = ROLE_TIME
                elif prep_text in ("because", "since", "as", "for",
                                   "due", "owing"):
                    role = ROLE_CAUSE
                else:
                    role = ROLE_THEME
            else:
                continue

            # Grab the subtree text for richer spans
            subtree_text = " ".join(t.text for t in child.subtree).strip()
            use_text = subtree_text if len(subtree_text) < 60 else span_text
            arguments.append(RoleArgument(
                role=role,
                text=use_text,
                span=(child.idx, child.idx + len(child.text)),
                confidence=0.80,
            ))

        if not arguments:
            continue

        frames.append(SRLFrame(
            predicate=token.lemma_,
            predicate_span=(token.idx, token.idx + len(token.text)),
            sentence=sent_text,
            arguments=arguments,
            confidence=0.80,
            source="spacy",
        ))

    return frames


# ---------------------------------------------------------------------------
# Main public class
# ---------------------------------------------------------------------------


class SRLExtractor:
    """Semantic Role Labeling extractor for event-centric knowledge graphs.

    Extracts predicate–argument structures from text and converts them into
    knowledge graph triples with semantic roles.

    Args:
        nlp: Optional spaCy ``Language`` model.  When provided, dependency-
             parse–based extraction is used; otherwise the heuristic fallback
             is used.
        min_confidence: Minimum confidence threshold for including frames.
        sentence_split: Whether to split text into sentences before extraction.

    Attributes:
        nlp: spaCy Language model (or ``None``).
        min_confidence: Confidence threshold.

    Example::

        extractor = SRLExtractor()
        frames = extractor.extract_srl("Alice sent the report to Bob.")
        kg = extractor.to_knowledge_graph(frames)
    """

    def __init__(
        self,
        nlp: Optional[Any] = None,
        min_confidence: float = 0.5,
        sentence_split: bool = True,
    ) -> None:
        self.nlp = nlp
        self.min_confidence = min_confidence
        self.sentence_split = sentence_split

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_srl(self, text: str) -> List[SRLFrame]:
        """Extract SRL frames from *text*.

        Args:
            text: Input text (one or more sentences).

        Returns:
            List of :class:`SRLFrame` objects, one per identified predicate.
        """
        if not text or not text.strip():
            return []

        if self.nlp is not None:
            return self._extract_with_spacy(text)
        return self._extract_heuristic(text)

    def to_knowledge_graph(
        self,
        frames: List[SRLFrame],
        kg: Optional[Any] = None,
    ) -> Any:
        """Convert SRL frames into a :class:`KnowledgeGraph`.

        Each frame becomes an ``Event`` entity; each role argument becomes a
        separate entity (or is merged if the same name already exists), and
        a typed relationship (``hasAgent``, ``hasPatient``, …) connects the
        event entity to the argument entity.

        Args:
            frames: SRL frames from :meth:`extract_srl`.
            kg:     Existing :class:`KnowledgeGraph` to extend, or ``None``
                    to create a new one.

        Returns:
            Populated :class:`KnowledgeGraph`.
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

        result_kg = kg if kg is not None else KnowledgeGraph(name="srl_graph")

        for frame in frames:
            if frame.confidence < self.min_confidence:
                continue

            # Create event entity
            event_entity = Entity(
                entity_type="Event",
                name=frame.predicate,
                properties={
                    "sentence": frame.sentence,
                    "source": frame.source,
                    "srl_frame_id": frame.frame_id,
                },
                confidence=frame.confidence,
            )
            result_kg.add_entity(event_entity)

            # Process each argument
            for arg in frame.arguments:
                if not arg.text.strip():
                    continue

                # Reuse existing entity with same (type, name) if present
                arg_entity_type = _role_to_entity_type(arg.role)
                existing = [
                    e for e in result_kg.get_entities_by_name(arg.text)
                    if e.entity_type == arg_entity_type
                ]
                if existing:
                    arg_entity = existing[0]
                else:
                    arg_entity = Entity(
                        entity_type=arg_entity_type,
                        name=arg.text,
                        confidence=arg.confidence,
                    )
                    result_kg.add_entity(arg_entity)

                rel_type = _ROLE_TO_RELATIONSHIP.get(arg.role, f"has{arg.role}")
                rel = Relationship(
                    relationship_type=rel_type,
                    source_entity=event_entity,
                    target_entity=arg_entity,
                    confidence=arg.confidence,
                    source_text=frame.sentence,
                )
                result_kg.add_relationship(rel)

        return result_kg

    def extract_batch(self, texts: List[str]) -> List[List[SRLFrame]]:
        """Extract SRL frames from a list of texts in one call.

        This is equivalent to calling :meth:`extract_srl` on each text
        individually, but is more ergonomic when processing collections.

        Args:
            texts: List of input strings.

        Returns:
            List of frame lists — one per input text, in the same order.
        """
        return [self.extract_srl(t) for t in texts]

    def build_temporal_graph(self, text: str) -> Any:
        """Extract events from *text* and link them with temporal relations.

        Temporal markers (``before``, ``after``, ``then``, ``subsequently``,
        ``first``, ``next``, etc.) between sentences are detected and
        represented as ``PRECEDES`` / ``FOLLOWS`` / ``OVERLAPS`` relationships
        in the returned event-centric KG.

        Args:
            text: Input text (multiple sentences recommended).

        Returns:
            :class:`KnowledgeGraph` with ``Event`` nodes and
            ``PRECEDES`` / ``FOLLOWS`` / ``OVERLAPS`` relationships.
        """
        frames = self.extract_srl(text)
        kg = self.to_knowledge_graph(frames)

        # ------------------------------------------------------------------
        # Temporal edge inference over sequential sentences
        # ------------------------------------------------------------------
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        # Group original frames by sentence text so frame IDs match the KG
        from collections import defaultdict as _defaultdict
        _frame_map: dict = _defaultdict(list)
        for _f in frames:
            _frame_map[_f.sentence.strip()].append(_f)
        # Build per-sentence frame list; fall back to extraction only when spaCy
        # is available and the sentence produced no frames during full-text pass.
        sent_frames: List[List[SRLFrame]] = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            sf = list(_frame_map.get(sent, []))
            if not sf and self.nlp is not None:
                doc = self.nlp(sent)
                sf = []
                for sp in doc.sents:
                    sf.extend(_extract_spacy_frames(sp))
            sent_frames.append(sf)

        # Temporal connector patterns between consecutive sentences
        _PRECEDES_RE = re.compile(
            r"\b(?:then|next|after(ward)?s?|subsequently|later|"
            r"following|thereafter|once)\b", re.I
        )
        _OVERLAPS_RE = re.compile(
            r"\b(?:meanwhile|simultaneously|at the same time|"
            r"during this|concurrently|while)\b", re.I
        )

        # Look at sentence pairs to create temporal links
        for i in range(len(sentences) - 1):
            sent_b = sentences[i + 1].strip() if i + 1 < len(sentences) else ""
            frames_a = sent_frames[i] if i < len(sent_frames) else []
            frames_b = sent_frames[i + 1] if i + 1 < len(sent_frames) else []

            if not frames_a or not frames_b:
                continue

            event_a_id = frames_a[0].frame_id
            event_b_id = frames_b[0].frame_id

            # Determine relationship type based on connector words
            if _OVERLAPS_RE.search(sent_b):
                rel_type = "OVERLAPS"
            elif _PRECEDES_RE.search(sent_b):
                rel_type = "PRECEDES"
            else:
                # Default: sequential sentences → first precedes second
                rel_type = "PRECEDES"

            # Look up the event entities in the KG
            from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
            from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

            ea = next(
                (e for e in kg.entities.values() if e.properties and e.properties.get("srl_frame_id") == event_a_id),
                None,
            )
            eb = next(
                (e for e in kg.entities.values() if e.properties and e.properties.get("srl_frame_id") == event_b_id),
                None,
            )
            if ea and eb:
                temporal_rel = Relationship(
                    relationship_type=rel_type,
                    source_entity=ea,
                    target_entity=eb,
                    confidence=0.65,
                    properties={"inferred_by": "temporal_srl"},
                )
                kg.add_relationship(temporal_rel)

        return kg

    def extract_to_triples(
        self, text: str
    ) -> List[Tuple[str, str, str]]:
        """Convenience method: extract text and return ``(subject, relation, object)`` triples.

        Args:
            text: Input text.

        Returns:
            List of ``(subject, predicate, object)`` string triples.
        """
        frames = self.extract_srl(text)
        triples: List[Tuple[str, str, str]] = []
        for frame in frames:
            agent = frame.get_role(ROLE_AGENT)
            patient = frame.get_role(ROLE_PATIENT) or frame.get_role(ROLE_THEME)
            if agent and patient:
                triples.append((agent.text, frame.predicate, patient.text))
        return triples

    # ------------------------------------------------------------------
    # Internal extraction backends
    # ------------------------------------------------------------------

    def _extract_with_spacy(self, text: str) -> List[SRLFrame]:
        """Use spaCy dependency parse for accurate SRL."""
        doc = self.nlp(text)
        frames: List[SRLFrame] = []
        for sent in doc.sents:
            sent_frames = _extract_spacy_frames(sent)
            frames.extend(
                f for f in sent_frames if f.confidence >= self.min_confidence
            )
        return frames

    def _extract_heuristic(self, text: str) -> List[SRLFrame]:
        """Use pure-Python heuristic SRL extraction."""
        if self.sentence_split:
            # Simple sentence splitter
            sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        else:
            sentences = [text]

        frames: List[SRLFrame] = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            sent_frames = _extract_heuristic_frames(sent)
            frames.extend(
                f for f in sent_frames if f.confidence >= self.min_confidence
            )
        return frames


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _role_to_entity_type(role: str) -> str:
    """Map a semantic role to a KG entity type."""
    mapping = {
        ROLE_AGENT: "Agent",
        ROLE_PATIENT: "Patient",
        ROLE_THEME: "Theme",
        ROLE_INSTRUMENT: "Instrument",
        ROLE_LOCATION: "Location",
        ROLE_TIME: "TimeExpression",
        ROLE_CAUSE: "Cause",
        ROLE_RESULT: "Result",
        ROLE_RECIPIENT: "Recipient",
        ROLE_SOURCE: "Source",
    }
    return mapping.get(role, "Entity")


__all__ = [
    "SRLExtractor",
    "SRLFrame",
    "RoleArgument",
    "ROLE_AGENT",
    "ROLE_PATIENT",
    "ROLE_THEME",
    "ROLE_INSTRUMENT",
    "ROLE_LOCATION",
    "ROLE_TIME",
    "ROLE_CAUSE",
    "ROLE_RESULT",
    "ROLE_RECIPIENT",
    "ROLE_SOURCE",
]
