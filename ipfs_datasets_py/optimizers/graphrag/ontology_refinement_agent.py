"""LLM-backed agent scaffolding for ontology refinement feedback."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class OntologyRefinementAgent:
    """Generate structured feedback using an LLM backend.

    This class is a lightweight scaffold that turns an ontology plus critic
    feedback into a structured feedback dict compatible with
    OntologyGenerator.generate_with_feedback().
    """

    def __init__(self, llm_backend: Any, logger: Optional[Any] = None) -> None:
        import logging as _logging

        self._log = logger or _logging.getLogger(__name__)
        self._llm_backend = llm_backend

    def build_prompt(self, ontology: Dict[str, Any], score: Any, context: Any) -> str:
        """Create a prompt asking for structured feedback as JSON."""
        entity_count = len(ontology.get("entities", []))
        relationship_count = len(ontology.get("relationships", []))
        recommendations = list(getattr(score, "recommendations", []) or [])

        lines = [
            "You are an ontology refinement agent.",
            f"Entities: {entity_count}, Relationships: {relationship_count}.",
            "Return JSON with any of these keys if applicable:",
            "- entities_to_remove (list of ids)",
            "- entities_to_merge (list of [id1, id2])",
            "- relationships_to_remove (list of ids)",
            "- relationships_to_add (list of relationship dicts)",
            "- type_corrections (map entity_id -> new_type)",
            "- confidence_floor (float)",
            "Recommendations:",
        ]
        for rec in recommendations[:10]:
            lines.append(f"- {rec}")
        return "\n".join(lines)

    def parse_feedback(self, response: Any) -> Dict[str, Any]:
        """Parse LLM response into a feedback dict."""
        if isinstance(response, dict):
            return response
        if not isinstance(response, str):
            return {}

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Attempt to extract JSON object from text
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(response[start : end + 1])
                except json.JSONDecodeError:
                    return {}
            return {}

    def propose_feedback(
        self,
        ontology: Dict[str, Any],
        score: Any,
        context: Any,
    ) -> Dict[str, Any]:
        """Call the LLM backend to propose structured feedback."""
        prompt = self.build_prompt(ontology, score, context)

        if self._llm_backend is None:
            return {}

        try:
            if callable(self._llm_backend):
                response = self._llm_backend(prompt)
            elif hasattr(self._llm_backend, "generate"):
                response = self._llm_backend.generate(prompt)
            elif hasattr(self._llm_backend, "complete"):
                response = self._llm_backend.complete(prompt)
            else:
                self._log.warning("Unsupported LLM backend interface")
                return {}
        except Exception as exc:
            self._log.warning("LLM backend invocation failed: %s", exc)
            return {}

        return self.parse_feedback(response)
