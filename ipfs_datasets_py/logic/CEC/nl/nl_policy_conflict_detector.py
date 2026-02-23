"""NL Policy Conflict Detector — BL122 (Phase 3c: conflict detection).

Detects conflicts in a compiled NL policy where the same action on the same
resource is simultaneously *permitted* and *prohibited* for the same actor.

Conflicts are classified as:
* ``"simultaneous_perm_prohib"`` — an action is both permitted and prohibited
* ``"multiple_obligations"`` — the same action is obligated more than once
  (not necessarily a hard conflict but may indicate intent mismatch)

Usage::

    from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
        NLPolicyConflictDetector, PolicyConflict, detect_conflicts,
    )
    from ipfs_datasets_py.logic.CEC.nl.nl_to_policy_compiler import NLToDCECCompiler

    compiler = NLToDCECCompiler()
    result = compiler.compile([
        "Alice may read all documents.",
        "Alice must not read any documents.",
    ])

    detector = NLPolicyConflictDetector()
    conflicts = detector.detect(result.clauses)
    for c in conflicts:
        print(c.conflict_type, c.action, c.actors)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PolicyConflict:
    """A detected conflict between policy clauses.

    Attributes
    ----------
    conflict_type:
        One of ``"simultaneous_perm_prohib"`` or ``"multiple_obligations"``.
    action:
        The action (or resource) that is in conflict (e.g. ``"read"``).
    resource:
        The resource name involved (may be ``"*"`` / wildcard).
    actors:
        Set of actors affected by this conflict.
    clause_types:
        The set of clause types involved (``"permission"``, ``"prohibition"``,
        ``"obligation"``).
    description:
        Human-readable conflict description.
    """

    conflict_type: str
    action: str
    resource: str = "*"
    actors: Set[str] = field(default_factory=set)
    clause_types: Set[str] = field(default_factory=set)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "conflict_type": self.conflict_type,
            "action": self.action,
            "resource": self.resource,
            "actors": sorted(self.actors),
            "clause_types": sorted(self.clause_types),
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class NLPolicyConflictDetector:
    """Detect conflicts in a list of compiled policy clauses.

    Parameters
    ----------
    wildcard:
        The wildcard string used for "any resource" / "any actor" matching.
        Defaults to ``"*"``.
    """

    def __init__(self, wildcard: str = "*") -> None:
        self._wildcard = wildcard

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, clauses: List[Any]) -> List[PolicyConflict]:
        """Detect conflicts in *clauses*.

        Parameters
        ----------
        clauses:
            List of ``PolicyClause``-like objects with at least:
            ``clause_type`` (``"permission"``/``"prohibition"``/``"obligation"``),
            ``action`` (str), ``actor`` (str or ``None``),
            ``resource`` (str or ``None``).

        Returns
        -------
        list of :class:`PolicyConflict`
            Empty list when no conflicts are detected.
        """
        return self._check_perm_prohib(clauses) + self._check_multiple_obligations(clauses)

    def detect_and_warn(
        self,
        clauses: List[Any],
        *,
        audit_log: Any = None,
        policy_cid: str = "nl_policy",
    ) -> List[PolicyConflict]:
        """BX134: Detect conflicts and emit :mod:`warnings` + optional audit entries.

        Parameters
        ----------
        clauses:
            Policy clause list (see :meth:`detect`).
        audit_log:
            Optional :class:`~mcp_server.policy_audit_log.PolicyAuditLog`.
            Each conflict is recorded as a ``"deny"`` entry with
            ``intent_cid="conflict:<conflict_type>"`` and
            ``actor="conflict_detector"``.
        policy_cid:
            Policy CID to use in audit entries.

        Returns
        -------
        list of :class:`PolicyConflict`
            Same as :meth:`detect`.
        """
        import warnings
        conflicts = self.detect(clauses)
        for conflict in conflicts:
            msg = (
                f"Policy conflict detected [{conflict.conflict_type}]: "
                f"{conflict.description}"
            )
            warnings.warn(msg, stacklevel=2)
            if audit_log is not None:
                try:
                    audit_log.record(
                        policy_cid=policy_cid,
                        intent_cid=f"conflict:{conflict.conflict_type}",
                        decision="deny",
                        tool=conflict.action,
                        actor="conflict_detector",
                    )
                except (TypeError, AttributeError, ValueError) as exc:
                    logger.debug("detect_and_warn: failed to record audit entry: %s", exc)
        return conflicts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, clause: Any) -> str:
        """Normalise action + resource into a conflict grouping key."""
        action = getattr(clause, "action", None) or "*"
        resource = getattr(clause, "resource", None) or "*"
        return f"{action}::{resource}"

    def _actor(self, clause: Any) -> str:
        actor = getattr(clause, "actor", None)
        return actor if actor else self._wildcard

    def _check_perm_prohib(self, clauses: List[Any]) -> List[PolicyConflict]:
        """Return one conflict per (action, resource) pair that has both a
        permission and a prohibition clause."""
        permissions: Dict[str, List[Any]] = {}
        prohibitions: Dict[str, List[Any]] = {}

        for c in clauses:
            ct = getattr(c, "clause_type", None)
            k = self._key(c)
            if ct == "permission":
                permissions.setdefault(k, []).append(c)
            elif ct == "prohibition":
                prohibitions.setdefault(k, []).append(c)

        conflicts: List[PolicyConflict] = []
        for k in set(permissions) & set(prohibitions):
            action, resource = k.split("::", 1)
            perm_clauses = permissions[k]
            prohib_clauses = prohibitions[k]

            # Collect all actors mentioned in both sides
            actors: Set[str] = set()
            for c in perm_clauses + prohib_clauses:
                actors.add(self._actor(c))

            # Only a real conflict when actor sets overlap (or either side
            # has a wildcard actor)
            wildcard = self._wildcard
            perm_actors = {self._actor(c) for c in perm_clauses}
            prohib_actors = {self._actor(c) for c in prohib_clauses}
            has_overlap = bool(perm_actors & prohib_actors) or \
                          wildcard in perm_actors or \
                          wildcard in prohib_actors

            if has_overlap:
                overlapping = actors if wildcard in actors else (perm_actors & prohib_actors)
                conflicts.append(
                    PolicyConflict(
                        conflict_type="simultaneous_perm_prohib",
                        action=action,
                        resource=resource,
                        actors=overlapping or actors,
                        clause_types={"permission", "prohibition"},
                        description=(
                            f"Action '{action}' on '{resource}' is both permitted "
                            f"and prohibited for actor(s) "
                            f"{sorted(overlapping or actors)!r}."
                        ),
                    )
                )
        return conflicts

    def _check_multiple_obligations(self, clauses: List[Any]) -> List[PolicyConflict]:
        """Return a conflict for each (action, resource, actor) triple that
        has more than one obligation clause (duplicate obligations)."""
        obligations: Dict[str, List[Any]] = {}
        for c in clauses:
            ct = getattr(c, "clause_type", None)
            if ct != "obligation":
                continue
            key = f"{self._key(c)}::{self._actor(c)}"
            obligations.setdefault(key, []).append(c)

        conflicts: List[PolicyConflict] = []
        for key, cs in obligations.items():
            if len(cs) > 1:
                parts = key.split("::", 2)
                action, resource = parts[0], parts[1]
                actor = parts[2] if len(parts) > 2 else self._wildcard
                conflicts.append(
                    PolicyConflict(
                        conflict_type="multiple_obligations",
                        action=action,
                        resource=resource,
                        actors={actor},
                        clause_types={"obligation"},
                        description=(
                            f"Action '{action}' on '{resource}' has {len(cs)} "
                            f"obligation clauses for actor '{actor}' — possible duplicate."
                        ),
                    )
                )
        return conflicts


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def detect_conflicts(
    clauses: List[Any],
    *,
    wildcard: str = "*",
) -> List[PolicyConflict]:
    """Shorthand: instantiate a :class:`NLPolicyConflictDetector` and call
    :meth:`~NLPolicyConflictDetector.detect`.

    Parameters
    ----------
    clauses:
        Policy clause list (see :meth:`~NLPolicyConflictDetector.detect`).
    wildcard:
        Wildcard string (default ``"*"``).

    Returns
    -------
    list of :class:`PolicyConflict`
    """
    return NLPolicyConflictDetector(wildcard=wildcard).detect(clauses)


# ---------------------------------------------------------------------------
# CB138 – i18n NL conflict scan (keyword-level, no clause compilation)
# ---------------------------------------------------------------------------

_I18N_KEYWORD_LOADERS: Dict[str, str] = {
    "fr": "ipfs_datasets_py.logic.CEC.nl.french_parser:get_french_deontic_keywords",
    "es": "ipfs_datasets_py.logic.CEC.nl.spanish_parser:get_spanish_deontic_keywords",
    "de": "ipfs_datasets_py.logic.CEC.nl.german_parser:get_german_deontic_keywords",
    "pt": "ipfs_datasets_py.logic.CEC.nl.portuguese_parser:get_portuguese_deontic_keywords",  # DJ172
}

# DC165: English deontic keywords (inline — no separate parser module needed).
_EN_DEONTIC_KEYWORDS: Dict[str, List[str]] = {
    "permission": [
        "may", "can", "is permitted", "is allowed", "is authorized",
        "has the right to", "is entitled to",
    ],
    "prohibition": [
        "must not", "cannot", "shall not", "is prohibited", "is forbidden",
        "is not allowed", "is not permitted",
    ],
    "obligation": [
        "must", "shall", "is required to", "is obligated to", "has to",
    ],
}

# DN176: Dutch deontic keywords (inline — no separate parser module needed).
_NL_DEONTIC_KEYWORDS: Dict[str, List[str]] = {
    "permission": [
        "mag", "kan", "is toegestaan", "is toegelaten", "heeft het recht om",
        "is gemachtigd", "is bevoegd",
    ],
    "prohibition": [
        "mag niet", "kan niet", "is verboden", "niet toegestaan",
        "is niet toegestaan", "is niet toegelaten", "niet gemachtigd",
    ],
    "obligation": [
        "moet", "dient", "is verplicht", "heeft de plicht om",
        "is vereist", "heeft de verplichting",
    ],
}


def _load_i18n_keywords(language: str) -> Dict[str, List[str]]:
    """Load deontic keywords for *language* (``"en"``, ``"nl"``, ``"fr"``, ``"es"``, ``"de"``, or ``"pt"``)."""
    if language == "en":  # DC165: inline English keywords
        return _EN_DEONTIC_KEYWORDS
    if language == "nl":  # DN176: inline Dutch keywords
        return _NL_DEONTIC_KEYWORDS
    loader_path = _I18N_KEYWORD_LOADERS.get(language)
    if loader_path is None:
        return {}
    module_path, func_name = loader_path.split(":")
    try:
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)
        return fn()
    except (ImportError, AttributeError):
        return {}


@dataclass
class I18NConflictResult:
    """Result of an i18n keyword-level conflict scan.

    Attributes
    ----------
    language:
        ISO 639-1 code of the language scanned (``"fr"``, ``"es"``, ``"de"``).
    has_permission:
        Whether any permission keyword was found.
    has_prohibition:
        Whether any prohibition keyword was found.
    has_simultaneous_conflict:
        ``True`` when *both* a permission **and** a prohibition keyword appear
        in the same text.
    matched_permission_keywords:
        Permission keywords found in the text.
    matched_prohibition_keywords:
        Prohibition keywords found in the text.
    """

    language: str
    has_permission: bool = False
    has_prohibition: bool = False
    has_simultaneous_conflict: bool = False
    matched_permission_keywords: List[str] = field(default_factory=list)
    matched_prohibition_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "has_permission": self.has_permission,
            "has_prohibition": self.has_prohibition,
            "has_simultaneous_conflict": self.has_simultaneous_conflict,
            "matched_permission_keywords": self.matched_permission_keywords,
            "matched_prohibition_keywords": self.matched_prohibition_keywords,
        }


def detect_i18n_conflicts(
    text: str,
    language: str = "fr",
) -> I18NConflictResult:
    """Scan *text* for simultaneous permission+prohibition keywords in *language*.

    This is a lightweight keyword-level scan — no full clause compilation is
    performed.  It is useful as a pre-filter before running the full
    :class:`NLPolicyConflictDetector`.

    Parameters
    ----------
    text:
        Raw natural language text to scan.
    language:
        ISO 639-1 language code.  Supported: ``"fr"``, ``"es"``, ``"de"``.

    Returns
    -------
    :class:`I18NConflictResult`
    """
    keywords = _load_i18n_keywords(language)
    text_lower = text.lower()

    perm_hits: List[str] = [
        kw for kw in keywords.get("permission", [])
        if kw.lower() in text_lower
    ]
    prohib_hits: List[str] = [
        kw for kw in keywords.get("prohibition", [])
        if kw.lower() in text_lower
    ]

    return I18NConflictResult(
        language=language,
        has_permission=bool(perm_hits),
        has_prohibition=bool(prohib_hits),
        has_simultaneous_conflict=bool(perm_hits) and bool(prohib_hits),
        matched_permission_keywords=perm_hits,
        matched_prohibition_keywords=prohib_hits,
    )


# ---------------------------------------------------------------------------
# CJ146: detect_i18n_clauses — full FR/ES/DE clause compilation + conflict detection
# ---------------------------------------------------------------------------

def detect_i18n_clauses(
    text: str,
    language: str = "fr",
) -> List["PolicyConflict"]:
    """CJ146: Compile *text* in *language* to deontic clauses, then detect policy conflicts.

    Unlike :func:`detect_i18n_conflicts` (lightweight keyword-scan only), this
    function performs **full deontic clause compilation** using the appropriate
    language parser (French / Spanish / German).  Each sentence is parsed into a
    :class:`~logic.CEC.nl.base_parser.DeonticFormula`, converted to a minimal
    clause object, and then fed to :class:`NLPolicyConflictDetector`.

    Parameters
    ----------
    text:
        Raw natural language text in the given *language*.
    language:
        ISO 639-1 language code.  Supported: ``"fr"``, ``"es"``, ``"de"``.

    Returns
    -------
    List[:class:`PolicyConflict`]
        Conflicts found in the compiled clauses.  An empty list is returned
        when no conflicts are found, the *language* is unsupported, or the
        language parser module is unavailable (ImportError).

    Notes
    -----
    If the language parser is unavailable (ImportError) or clause compilation
    fails, an empty list is returned and the error is logged at DEBUG level.
    """
    _LANG_PARSER_MAP = {
        "fr": ("ipfs_datasets_py.logic.CEC.nl.french_parser", "FrenchParser"),
        "es": ("ipfs_datasets_py.logic.CEC.nl.spanish_parser", "SpanishParser"),
        "de": ("ipfs_datasets_py.logic.CEC.nl.german_parser", "GermanParser"),
    }

    module_path, class_name = _LANG_PARSER_MAP.get(language, (None, None))
    if module_path is None:
        logger.debug("detect_i18n_clauses: unsupported language %r", language)
        return []

    try:
        import importlib
        parser_mod = importlib.import_module(module_path)
        parser_cls = getattr(parser_mod, class_name)
        parser = parser_cls()
    except (ImportError, AttributeError) as exc:
        logger.debug("detect_i18n_clauses: parser unavailable for %r: %s", language, exc)
        return []

    # Parse text into DeonticFormulas, then convert to PolicyClauses
    try:
        sentences = [s.strip() for s in text.replace(";", ".").replace("!", ".").split(".") if s.strip()]
        clauses: List[Any] = []
        for sentence in sentences:
            try:
                formula = parser.parse(sentence)
                if formula is not None:
                    # Convert DeonticFormula → PolicyClause-like dict for conflict detection
                    op = getattr(formula, "operator", None)
                    if op is None:
                        continue
                    op_name = op.value.lower() if hasattr(op, "value") else str(op).lower()
                    clause_type = {
                        "permission": "permission",
                        "obligation": "obligation",
                        "prohibition": "prohibition",
                    }.get(op_name)
                    if clause_type is None:
                        continue
                    action = getattr(formula, "action", "*") or "*"
                    resource = getattr(formula, "resource", "*") or "*"
                    actor = getattr(formula, "subject", "*") or "*"

                    # Build a minimal clause-compatible dict
                    class _Clause:
                        def __init__(self, ct: str, a: str, r: str, ac: str) -> None:
                            self.clause_type = ct
                            self.action = a
                            self.resource = r
                            self.actor = ac

                    clauses.append(_Clause(clause_type, action, resource, actor))
            except Exception as exc:
                logger.debug("detect_i18n_clauses: parse error for sentence %r: %s", sentence, exc)

        detector = NLPolicyConflictDetector()
        return detector.detect(clauses)
    except Exception as exc:
        logger.debug("detect_i18n_clauses: detection failed: %s", exc)
        return []
