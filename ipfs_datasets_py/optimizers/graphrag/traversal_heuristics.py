"""Heuristic helpers for GraphRAG traversal optimization."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class TraversalHeuristics:
    """Pure heuristic detectors and estimators used by traversal optimizers."""

    WIKIPEDIA_RELATION_IMPORTANCE = {
        "instance_of": 0.95,
        "subclass_of": 0.92,
        "type_of": 0.90,
        "category": 0.90,
        "part_of": 0.88,
        "has_part": 0.85,
        "contains": 0.85,
        "component_of": 0.83,
        "member_of": 0.82,
        "has_member": 0.82,
        "located_in": 0.79,
        "capital_of": 0.78,
        "headquarters_in": 0.78,
        "geographical_location": 0.75,
        "neighbor_of": 0.72,
        "created_by": 0.69,
        "developer": 0.68,
        "author": 0.67,
        "invented_by": 0.65,
        "founder": 0.65,
        "preceded_by": 0.62,
        "followed_by": 0.62,
        "influenced": 0.60,
        "function": 0.58,
        "used_for": 0.57,
        "works_on": 0.55,
        "employed_by": 0.55,
        "opposite_of": 0.53,
        "similar_to": 0.52,
        "related_to": 0.45,
        "associated_with": 0.42,
        "see_also": 0.40,
        "different_from": 0.35,
        "same_as": 0.35,
        "externally_linked": 0.32,
        "link": 0.30,
        "described_by": 0.30,
    }

    @staticmethod
    def detect_query_relations(query_text: str) -> List[str]:
        """Extract likely relation types from free-text query content."""
        query_relations: List[str] = []
        if not query_text:
            return query_relations

        query_text_lower = query_text.lower()

        if any(term in query_text_lower for term in ["type", "instance", "is a", "example of"]):
            query_relations.append("instance_of")

        if any(term in query_text_lower for term in ["part", "component", "contain", "within", "inside"]):
            query_relations.append("part_of")

        if any(term in query_text_lower for term in ["located", "where", "place", "location"]):
            query_relations.append("located_in")

        if any(term in query_text_lower for term in ["created", "made", "developed", "authored", "wrote"]):
            query_relations.append("created_by")

        if any(term in query_text_lower for term in ["similar", "like", "analogous"]):
            query_relations.append("similar_to")

        return query_relations

    @staticmethod
    def detect_fact_verification_query(query: Dict[str, Any]) -> bool:
        """Detect if a query likely asks for fact verification."""
        query_blob = str(query).lower()

        if "verification" in query_blob:
            return True

        if "source_entity" in query and "target_entity" in query:
            return True

        if "query_text" in query:
            query_text = query["query_text"].lower()
            fact_patterns = [
                "is it true that", "verify if", "check if", "is there a connection between",
                "are", "is", "did", "was", "were", "do", "does", "has", "have",
                "connected to", "related to", "linked to", "correct that", "accurate that",
                "prove", "disprove", "evidence for", "support for", "refute"
            ]

            if any(query_text.startswith(word) for word in ["is", "are", "was", "were", "do", "does", "did", "has", "have", "can", "could", "should", "would"]):
                return True

            if any(pattern in query_text for pattern in fact_patterns):
                return True

            comparison_patterns = ["same as", "different from", "equivalent to", "similar to", "unlike"]
            if any(pattern in query_text for pattern in comparison_patterns):
                return True

        return False

    @staticmethod
    def detect_exploratory_query(query: Dict[str, Any]) -> bool:
        """Detect if a query is broad/exploratory rather than specific."""
        query_blob = str(query).lower()

        if any(term in query_blob for term in ["exploration", "discover", "survey", "overview"]):
            return True

        if "query_text" in query:
            query_text = query["query_text"].lower()
            exploratory_patterns = [
                "what are", "tell me about", "explain", "describe", "overview of",
                "introduction to", "discover", "explore", "information about",
                "learn about", "show me", "find", "search for", "list", "examples of",
                "types of", "kinds of", "ways to", "methods of", "approaches to"
            ]

            if any(pattern in query_text for pattern in exploratory_patterns):
                return True

            if query_text.startswith(("what", "how", "why")) and len(query_text.split()) < 6:
                return True

        if "traversal" in query and query["traversal"].get("max_depth", 0) > 3:
            if "target_entity" not in query and "entity_ids" not in query:
                return True

        if "vector_params" in query and query["vector_params"].get("top_k", 0) > 10:
            return True

        return False

    @staticmethod
    def detect_entity_types(query_text: str, predefined_types: Optional[List[str]] = None) -> List[str]:
        """Detect likely entity types from query text."""
        if predefined_types:
            return predefined_types

        if not query_text:
            return []

        text = query_text.lower()
        detected_types: List[str] = []

        person_patterns = [
            "who", "person", "people", "author", "writer", "creator", "founder",
            "born", "died", "age", "biography", "invented", "discovered",
            "president", "king", "queen", "actor", "actress", "director",
            "scientist", "artist", "musician", "politician", "athlete"
        ]

        organization_patterns = [
            "company", "organization", "corporation", "business", "firm", "agency",
            "university", "school", "college", "institution", "government", "team",
            "founded", "headquarters", "ceo", "employees", "products", "services"
        ]

        location_patterns = [
            "where", "place", "location", "country", "city", "state", "region",
            "continent", "area", "located", "capital", "geography", "landmark",
            "mountain", "river", "ocean", "lake", "island", "territory", "border"
        ]

        concept_patterns = [
            "what", "concept", "theory", "idea", "principle", "definition",
            "meaning", "philosophy", "method", "system", "field", "discipline",
            "explain", "describe", "define", "understand", "how does", "how is"
        ]

        event_patterns = [
            "when", "event", "happened", "occurred", "took place", "date",
            "history", "war", "battle", "conference", "meeting", "election",
            "ceremony", "festival", "disaster", "revolution", "movement"
        ]

        product_patterns = [
            "product", "device", "technology", "tool", "software", "hardware",
            "machine", "vehicle", "book", "album", "movie", "film", "game",
            "service", "brand", "model", "version", "release", "launched"
        ]

        if any(pattern in text for pattern in person_patterns):
            detected_types.append("person")

        if any(pattern in text for pattern in organization_patterns):
            detected_types.append("organization")

        if any(pattern in text for pattern in location_patterns):
            detected_types.append("location")

        if any(pattern in text for pattern in concept_patterns):
            detected_types.append("concept")

        if any(pattern in text for pattern in event_patterns):
            detected_types.append("event")

        if any(pattern in text for pattern in product_patterns):
            detected_types.append("product")

        if not detected_types:
            detected_types.append("concept")

        return detected_types

    @staticmethod
    def estimate_query_complexity(query: Dict[str, Any]) -> str:
        """Estimate query complexity for traversal optimization decisions."""
        complexity_score = 0

        if "vector_params" in query:
            vector_params = query["vector_params"]
            complexity_score += min(5, vector_params.get("top_k", 5) * 0.5)

        if "traversal" in query:
            traversal = query["traversal"]
            max_depth = traversal.get("max_depth", 2)
            complexity_score += max_depth * 2

            edge_types = traversal.get("edge_types", [])
            complexity_score += min(5, len(edge_types) * 0.5)

        if "query_text" in query:
            query_text = query["query_text"]
            complexity_score += min(3, len(query_text.split()) / 10)

            entity_count = len(query.get("entity_ids", []))
            complexity_score += min(3, entity_count * 0.5)

        if complexity_score < 5:
            return "low"
        elif complexity_score < 10:
            return "medium"
        else:
            return "high"