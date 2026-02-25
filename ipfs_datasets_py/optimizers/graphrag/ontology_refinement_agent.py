"""LLM-backed agent scaffolding for ontology refinement feedback."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, cast, runtime_checkable

from ..common.backend_resilience import BackendCallPolicy, execute_with_resilience
from ..common.circuit_breaker import CircuitBreaker
from ..common.exceptions import CircuitBreakerOpenError, RetryableBackendError


@runtime_checkable
class RefinementAgentProtocol(Protocol):
    """Protocol for refinement agents used by OntologyMediator."""

    def propose_feedback(
        self,
        ontology: Dict[str, Any],
        score: Any,
        context: Any,
    ) -> Dict[str, Any]:
        """Return structured feedback for refinement."""


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_pair_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return False
        if not all(isinstance(entry, str) for entry in item):
            return False
    return True


def _is_relationship_list(value: Any, strict: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        if strict:
            if not (item.get("source_id") and item.get("target_id") and item.get("type")):
                return False
    return True


def _is_type_corrections(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())


def validate_feedback_schema(feedback: Any, *, strict: bool = False) -> List[str]:
    """Validate a feedback dict for refinement.

    Returns a list of human-readable error messages.
    """
    errors: List[str] = []
    if not isinstance(feedback, dict):
        return ["feedback must be a dict"]

    allowed = {
        "entities_to_remove",
        "entities_to_merge",
        "relationships_to_remove",
        "relationships_to_add",
        "type_corrections",
        "confidence_floor",
    }

    for key in feedback:
        if key not in allowed:
            errors.append(f"unsupported feedback key: {key}")

    if "entities_to_remove" in feedback and not _is_str_list(feedback["entities_to_remove"]):
        errors.append("entities_to_remove must be a list of strings")
    if "entities_to_merge" in feedback and not _is_pair_list(feedback["entities_to_merge"]):
        errors.append("entities_to_merge must be a list of [id1, id2] pairs")
    if "relationships_to_remove" in feedback and not _is_str_list(feedback["relationships_to_remove"]):
        errors.append("relationships_to_remove must be a list of strings")
    if "relationships_to_add" in feedback and not _is_relationship_list(
        feedback["relationships_to_add"], strict=strict
    ):
        errors.append("relationships_to_add must be a list of dicts")
    if "type_corrections" in feedback and not _is_type_corrections(feedback["type_corrections"]):
        errors.append("type_corrections must be a dict[str, str]")
    if "confidence_floor" in feedback and not isinstance(feedback["confidence_floor"], (int, float)):
        errors.append("confidence_floor must be a number")
    if strict and "confidence_floor" in feedback:
        if not (0.0 <= float(feedback["confidence_floor"]) <= 1.0):
            errors.append("confidence_floor must be in [0.0, 1.0]")

    return errors


def sanitize_feedback(feedback: Any, *, strict: bool = False) -> Tuple[Dict[str, Any], List[str]]:
    """Return a validated feedback dict and any schema errors."""
    if not isinstance(feedback, dict):
        return {}, ["feedback must be a dict"]

    errors = validate_feedback_schema(feedback, strict=strict)
    if not errors:
        return dict(feedback), []

    cleaned: Dict[str, Any] = {}
    if "entities_to_remove" in feedback and _is_str_list(feedback["entities_to_remove"]):
        cleaned["entities_to_remove"] = feedback["entities_to_remove"]
    if "entities_to_merge" in feedback and _is_pair_list(feedback["entities_to_merge"]):
        cleaned["entities_to_merge"] = feedback["entities_to_merge"]
    if "relationships_to_remove" in feedback and _is_str_list(feedback["relationships_to_remove"]):
        cleaned["relationships_to_remove"] = feedback["relationships_to_remove"]
    if "relationships_to_add" in feedback and _is_relationship_list(
        feedback["relationships_to_add"], strict=strict
    ):
        cleaned["relationships_to_add"] = feedback["relationships_to_add"]
    if "type_corrections" in feedback and _is_type_corrections(feedback["type_corrections"]):
        cleaned["type_corrections"] = feedback["type_corrections"]
    if "confidence_floor" in feedback and isinstance(feedback["confidence_floor"], (int, float)):
        cleaned["confidence_floor"] = feedback["confidence_floor"]

    return cleaned, errors


class OntologyRefinementAgent:
    """Generate structured feedback using an LLM backend.

    This class is a lightweight scaffold that turns an ontology plus critic
    feedback into a structured feedback dict compatible with
    OntologyGenerator.generate_with_feedback().
    """

    def __init__(
        self,
        llm_backend: Any,
        logger: Optional[Any] = None,
        *,
        strict_validation: bool = False,
        backend_call_policy: Optional[BackendCallPolicy] = None,
    ) -> None:
        import logging as _logging

        self._log = logger or _logging.getLogger(__name__)
        self._llm_backend = llm_backend
        self._strict_validation = strict_validation
        self._backend_call_policy = backend_call_policy or BackendCallPolicy(
            service_name="graphrag_refinement_llm",
            timeout_seconds=15.0,
            max_retries=2,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
            max_backoff_seconds=1.0,
            circuit_failure_threshold=5,
            circuit_recovery_timeout=60.0,
        )
        self._backend_circuit_breaker: CircuitBreaker[Any] = CircuitBreaker(
            name=self._backend_call_policy.service_name,
            failure_threshold=self._backend_call_policy.circuit_failure_threshold,
            recovery_timeout=self._backend_call_policy.circuit_recovery_timeout,
            expected_exception=Exception,
        )

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
            parsed = json.loads(response)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            # Attempt to extract JSON object from text
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(response[start : end + 1])
                    return parsed if isinstance(parsed, dict) else {}
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

        backend_call = self._resolve_backend_call()
        if backend_call is None:
            return {}

        try:
            response = execute_with_resilience(
                lambda: backend_call(prompt),
                self._backend_call_policy,
                circuit_breaker=self._backend_circuit_breaker,
            )
        except (CircuitBreakerOpenError, RetryableBackendError) as exc:
            self._log.warning("LLM backend invocation failed: %s", exc)
            return {}

        parsed = self.parse_feedback(response)
        cleaned, errors = sanitize_feedback(parsed, strict=self._strict_validation)
        if errors:
            self._log.warning("Invalid feedback schema: %s", errors)
        return cleaned

    def _resolve_backend_call(self) -> Optional[Callable[[str], Any]]:
        """Resolve supported backend interfaces to a single callable."""
        if self._llm_backend is None:
            return None
        if callable(self._llm_backend):
            return cast(Callable[[str], Any], self._llm_backend)

        generate_method = getattr(self._llm_backend, "generate", None)
        if callable(generate_method):
            return cast(Callable[[str], Any], generate_method)

        complete_method = getattr(self._llm_backend, "complete", None)
        if callable(complete_method):
            return cast(Callable[[str], Any], complete_method)

        self._log.warning("Unsupported LLM backend interface")
        return None


class NoOpRefinementAgent:
    """Deterministic refinement agent for tests and offline runs.

    Returns a fixed feedback payload on every call to avoid nondeterminism.
    """

    def __init__(self, feedback: Optional[Dict[str, Any]] = None) -> None:
        self._feedback = dict(feedback or {})

    def propose_feedback(
        self,
        ontology: Dict[str, Any],
        score: Any,
        context: Any,
    ) -> Dict[str, Any]:
        cleaned, _ = sanitize_feedback(self._feedback)
        return cleaned
