"""The duty-bearer and each nested body are both actors.

``the Person ... of the Electors`` has two actors: the person who must act,
and the Electors. ``the House of Representatives`` likewise has the House
and the Representatives. Each actor is an F-logic frame and a knowledge-graph
entity. A stored sort becomes ``isa``. A missing sort does not remove the
frame or the entity, and it is not filled by the keyword classifier.
Nothing here is an admit, and nothing here is written into a CanonicalRule.
"""

from __future__ import annotations

import re
from typing import Any


# "of the Electors", "of Representatives", "by the House". The phrase United
# States is the jurisdiction name, not an office-holder nested in the subject.
_EMBEDDED_ACTOR_RE = re.compile(
    r"\b(?:of|by|from)\s+(?:the\s+)?(?P<actor>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)"
)
_JURISDICTION = frozenset({"united states", "united states of america"})


def _lemma(surface: str) -> str:
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", str(surface or "")).split()).lower()


def embedded_actor_surfaces(text: str, *, subject: str = "") -> list[str]:
    """Nested bodies after of/by/from. They are actors in addition to ``subject``.

    ``House`` in ``House of Representatives`` is the head of the duty-bearer,
    so it is not a second actor. ``Representatives`` is.
    """

    subject_key = _lemma(subject)
    found: list[str] = []
    seen: set[str] = set()
    for match in _EMBEDDED_ACTOR_RE.finditer(str(text or "")):
        surface = " ".join(match.group("actor").split())
        key = _lemma(surface)
        if not key or key in _JURISDICTION or key in seen:
            continue
        if subject_key and (key == subject_key or subject_key.startswith(key + " ")):
            continue
        seen.add(key)
        found.append(surface)
    return found


def duty_subject(text: str) -> str:
    """Grammatical subject of the first modal. Not an embedded body."""

    from ipfs_datasets_py.logic.deontic import DeonticConverter

    try:
        converted = DeonticConverter(
            jurisdiction="us",
            document_type="statute",
            use_ml=False,
            use_cache=False,
            enable_monitoring=False,
        ).convert(text)
    except (OSError, ValueError, TypeError):
        return ""
    elements = list(getattr(getattr(converted, "output", None), "parser_elements", ()) or [])
    for element in elements:
        if not isinstance(element, dict):
            continue
        subjects = [item for item in element.get("subject") or [] if str(item).strip()]
        if subjects:
            return " ".join(str(subjects[0]).split())
    return ""


def clause_actors(text: str) -> list[dict[str, str]]:
    """Duty-bearer and nested bodies. Both are actors. Sorts are not invented."""

    duty = duty_subject(text)
    actors: list[dict[str, str]] = []
    seen: set[str] = set()
    if duty and _lemma(duty) not in _JURISDICTION:
        actors.append({"surface": duty, "role": "duty"})
        seen.add(_lemma(duty))
    for surface in embedded_actor_surfaces(text, subject=duty):
        key = _lemma(surface)
        if key in seen:
            continue
        seen.add(key)
        actors.append({"surface": surface, "role": "embedded"})
    return actors


def actor_triples(span_id: str, actors: list[dict[str, str]], sorts: dict[str, str] | None = None) -> list[dict[str, str]]:
    """One frame subject per actor, plus a span edge to that entity.

    ``sorts`` maps a lemma to a caller-supplied sort. It does not invent one.
    """

    span = str(span_id or "clause")
    known = { _lemma(key): _lemma(value) for key, value in (sorts or {}).items() }
    triples: list[dict[str, str]] = []
    for actor in actors:
        lemma = _lemma(actor.get("surface") or "")
        role = str(actor.get("role") or "")
        if not lemma or not role:
            continue
        triples.append({"subject": lemma, "predicate": "role", "object": role})
        triples.append({"subject": span, "predicate": "actor", "object": lemma})
        sort_id = known.get(lemma) or ""
        if sort_id:
            triples.append({"subject": lemma, "predicate": "type", "object": sort_id})
    return triples


class EmbeddedActorFixture:
    """Both actors are frames and entities. A sort is stored only when supplied."""

    def __init__(self, repository: Any = None) -> None:
        if repository is None:
            from ipfs_datasets_py.logic.proof_corpus.duckdb_repository import (
                ProofCorpusDuckDBRepository,
            )

            repository = ProofCorpusDuckDBRepository()
        self.repository = repository
        self._by_lemma: dict[str, dict[str, str]] = {}

    def put(self, *, span_id: str, surface: str, sort_id: str) -> dict[str, Any]:
        lemma = _lemma(surface)
        sort_id = _lemma(sort_id)
        if not span_id or not lemma or not sort_id:
            return {"result": "abstain", "reason": "no_embedded_actor", "admitted": False}
        stored = self._by_lemma.get(lemma)
        if stored is not None and stored["sort_id"] != sort_id:
            return {
                "result": "no",
                "reason": "sort_mismatch",
                "surface": surface,
                "admitted": False,
            }
        frame = {"surface": surface, "isa": sort_id, "span_id": span_id}
        edge = {"subject": span_id, "predicate": "actor", "object": lemma}
        frame_record = self.repository.put_attestation(
            frame,
            subject_cid=f"embedded-actor-frame:{lemma}",
            family="flogic",
            profile="embedded_actor_frame",
        )
        edge_record = self.repository.put_attestation(
            edge,
            subject_cid=f"embedded-actor-edge:{span_id}:{lemma}",
            family="graph",
            profile="embedded_actor_edge",
        )
        row = {
            "span_id": span_id,
            "surface": surface,
            "lemma": lemma,
            "sort_id": sort_id,
            "flogic_frame_cid": frame_record.content_cid,
            "graph_edge_cid": edge_record.content_cid,
        }
        self.repository.put_attestation(
            row,
            subject_cid=f"embedded-actor-map:{lemma}",
            family="embedded_actor",
            profile="embedded_actor_map",
        )
        self._by_lemma[lemma] = row
        return {"result": "yes", "admitted": False, **row}

    def slot(self, text: str, *, span_id: str = "") -> dict[str, Any]:
        mentions = embedded_actor_surfaces(text)
        if not mentions:
            return {"result": "abstain", "reason": "no_embedded_actor", "admitted": False, "actors": []}
        mapped: list[dict[str, str]] = []
        unmapped: list[str] = []
        for surface in mentions:
            row = self._by_lemma.get(_lemma(surface))
            if row is None or not self._cids_resolve(row):
                unmapped.append(surface)
                continue
            if span_id and row["span_id"] != span_id:
                unmapped.append(surface)
                continue
            mapped.append({
                "surface": surface,
                "sort_id": row["sort_id"],
                "frame_cid": row["flogic_frame_cid"],
                "edge_cid": row["graph_edge_cid"],
            })
        if not mapped:
            return {
                "result": "abstain",
                "reason": "unmapped",
                "actors": [],
                "unmapped": unmapped,
                "admitted": False,
            }
        return {
            "result": "yes",
            "reason": "",
            "actors": mapped,
            "unmapped": unmapped,
            "admitted": False,
        }

    def triples(self, span_id: str, text: str = "") -> list[dict[str, str]]:
        """Frames for every actor in ``text``. Sorts only where ``put`` stored one."""

        actors = clause_actors(text) if text else []
        if not actors:
            actors = [
                {"surface": row["surface"], "role": "embedded"}
                for row in self._by_lemma.values()
                if row["span_id"] == span_id
            ]
        sorts = {
            row["lemma"]: row["sort_id"]
            for row in self._by_lemma.values()
            if row["span_id"] == span_id
        }
        return actor_triples(span_id, actors, sorts)

    def project(self, text: str, *, span_id: str) -> dict[str, Any]:
        """F-logic frames and knowledge-graph entities for both actors."""

        from ipfs_datasets_py.logic.modal.kg_bridge import (
            flogic_triples_to_graph_data,
            flogic_triples_to_ontology,
        )

        actors = clause_actors(text)
        triples = self.triples(span_id, text)
        for actor in actors:
            actor["sort_id"] = next(
                (
                    triple["object"]
                    for triple in triples
                    if triple["subject"] == _lemma(actor["surface"]) and triple["predicate"] == "type"
                ),
                "",
            )
            actor["admitted"] = False
        return {
            "actors": actors,
            "triples": triples,
            "flogic": flogic_triples_to_ontology(triples, name=f"{span_id}_actors"),
            "graph": flogic_triples_to_graph_data(
                triples,
                augment_sparse_legal_projection=False,
                graph_id=f"{span_id}:actors",
            ),
            "admitted": False,
        }

    def flogic(self, span_id: str, text: str = "") -> Any:
        """F-logic frames. ``type`` becomes ``isa``. Each actor is a frame."""

        from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_ontology

        return flogic_triples_to_ontology(
            self.triples(span_id, text),
            name=f"{span_id}_actors",
        )

    def knowledge_graph(self, span_id: str, text: str = "") -> Any:
        """One-hop graph. Each actor is an entity. No dense projection."""

        from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

        return flogic_triples_to_graph_data(
            self.triples(span_id, text),
            augment_sparse_legal_projection=False,
            graph_id=f"{span_id}:actors",
        )

    def _cids_resolve(self, row: dict[str, str]) -> bool:
        for key in ("flogic_frame_cid", "graph_edge_cid"):
            cid = str(row.get(key) or "")
            if not cid:
                return False
            try:
                body = self.repository.blob_store.get_bytes(cid)
            except Exception:
                return False
            if not body:
                return False
        return True
