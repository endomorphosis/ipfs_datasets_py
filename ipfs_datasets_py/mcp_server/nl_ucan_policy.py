"""Natural-Language → UCAN Policy Compiler (MCP++ Profile D extension).

Turns a natural-language policy string into a ``PolicyObject`` (Profile D) that
can gate access to MCP tools through a :class:`UCANPolicyGate`.

Design principles
-----------------
1. **Open by default** — with no registered policies every intent is allowed.
2. **Opt-in** — users choose to attach an NL policy to a gate instance; tools
   not covered by any registered policy remain open.
3. **Hash-validated recompilation** — each compiled policy stores a SHA-256
   digest of its source NL text. At evaluation time the gate re-hashes the
   stored source and, if the digest differs (source was mutated), recompiles
   before evaluating.
4. **Logic module integration** — compilation uses the
   :class:`~ipfs_datasets_py.logic.deontic.converter.DeonticConverter` when the
   ``ipfs_datasets_py.logic`` package is available. A pure-Python fallback
   parser handles the common English policy idioms when the logic module is
   absent or unavailable.

Typical usage::

    from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
        NLUCANPolicyCompiler, UCANPolicyGate,
    )
    from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject

    compiler = NLUCANPolicyCompiler()
    gate = UCANPolicyGate(compiler)

    # Register an NL policy (opt-in)
    gate.register_policy(
        name="admin_only",
        nl_policy="Only the admin role may call the admin_tools category tools.",
    )

    # At dispatch time — open to everyone if no policy registered
    intent = IntentObject(interface_cid="bafy-...", tool="some_tool",
                         input_cid="bafy-...")
    decision = gate.evaluate(intent, actor="alice")  # "allow" (no matching policy)
    decision = gate.evaluate(intent, actor="admin")  # "allow" (matches permission)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .cid_artifacts import DecisionObject, IntentObject, artifact_cid
from .temporal_policy import (
    PolicyClause,
    PolicyEvaluator,
    PolicyObject,
    make_simple_permission_policy,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class NLPolicySource:
    """Stores an NL policy string together with its content hash.

    Attributes:
        text: The raw natural-language policy text.
        source_hash: SHA-256 hex digest of *text* (computed at construction).
    """

    text: str
    source_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.source_hash = _sha256_text(self.text)

    def hash_matches(self, candidate_hash: str) -> bool:
        """Return ``True`` if *candidate_hash* matches the stored source hash."""
        return self.source_hash == candidate_hash


@dataclass
class CompiledUCANPolicy:
    """A compiled policy derived from an NL source.

    Attributes:
        policy: The :class:`~temporal_policy.PolicyObject` produced by
            the compiler.
        source_hash: SHA-256 digest of the NL text used during compilation.
            Used to detect stale compilations.
        compiled_at: ISO-8601 UTC timestamp of when compilation completed.
        compiler_version: Version tag of the compiler that produced this policy.
        metadata: Freeform compilation metadata (clause counts, strategy, …).
    """

    policy: PolicyObject
    source_hash: str
    compiled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    compiler_version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_stale(self) -> bool:
        """``True`` when this object has no clauses (trivially stale)."""
        return not self.policy.clauses

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (for storage / CID computation)."""
        return {
            "policy": self.policy.to_dict(),
            "source_hash": self.source_hash,
            "compiled_at": self.compiled_at,
            "compiler_version": self.compiler_version,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Fallback parser (no logic module required)
# ---------------------------------------------------------------------------

_PERMISSION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # "only <actor> may/can/is allowed to <action>"
    (
        re.compile(
            r"only\s+(?P<actor>\S+)\s+(?:may|can|is allowed to)\s+(?:call\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "permission",
    ),
    # "<actor> may/can <action>"
    (
        re.compile(
            r"(?P<actor>\S+)\s+(?:may|can)\s+(?:call\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "permission",
    ),
    # "<actor> is permitted to <action>"
    (
        re.compile(
            r"(?P<actor>\S+)\s+is permitted to\s+(?:call\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "permission",
    ),
]

_PROHIBITION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # "<actor> must not / shall not / may not <action>"
    (
        re.compile(
            r"(?P<actor>\S+)\s+(?:must not|shall not|may not|cannot)\s+(?:call\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "prohibition",
    ),
    # "<actor> is prohibited from <action>"
    (
        re.compile(
            r"(?P<actor>\S+)\s+is prohibited from\s+(?:calling\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "prohibition",
    ),
    # "no <actor> may <action>"
    (
        re.compile(
            r"no\s+(?P<actor>\S+)\s+(?:may|can)\s+(?:call\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "prohibition",
    ),
]

_OBLIGATION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # "<actor> must/shall <action>"
    (
        re.compile(
            r"(?P<actor>\S+)\s+(?:must|shall)\s+(?:call\s+)?(?P<action>\S+)",
            re.IGNORECASE,
        ),
        "obligation",
    ),
]


def _fallback_parse_nl_policy(nl_text: str) -> List[PolicyClause]:
    """Parse *nl_text* using simple regex patterns into policy clauses.

    This is a best-effort heuristic that handles the most common English policy
    idioms (permission / prohibition / obligation). It is used as a fallback
    when the :mod:`ipfs_datasets_py.logic` module is unavailable.

    Args:
        nl_text: Raw natural-language policy text.

    Returns:
        A (possibly empty) list of :class:`~temporal_policy.PolicyClause` objects.
    """
    clauses: List[PolicyClause] = []
    sentences = re.split(r"[.;!?\n]+", nl_text)

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        matched = False

        # Check prohibition first (higher specificity)
        for pattern, clause_type in _PROHIBITION_PATTERNS:
            m = pattern.search(sentence)
            if m:
                clauses.append(
                    PolicyClause(
                        clause_type=clause_type,
                        actor=m.group("actor").lower(),
                        action=m.group("action").lower(),
                    )
                )
                matched = True
                break

        if matched:
            continue

        # Check obligation
        for pattern, clause_type in _OBLIGATION_PATTERNS:
            m = pattern.search(sentence)
            if m:
                clauses.append(
                    PolicyClause(
                        clause_type=clause_type,
                        actor=m.group("actor").lower(),
                        action=m.group("action").lower(),
                    )
                )
                matched = True
                break

        if matched:
            continue

        # Check permission last
        for pattern, clause_type in _PERMISSION_PATTERNS:
            m = pattern.search(sentence)
            if m:
                clauses.append(
                    PolicyClause(
                        clause_type=clause_type,
                        actor=m.group("actor").lower(),
                        action=m.group("action").lower(),
                    )
                )
                break

    return clauses


# ---------------------------------------------------------------------------
# Logic-module integration
# ---------------------------------------------------------------------------

def _try_logic_module_compile(nl_text: str) -> Optional[List[PolicyClause]]:
    """Attempt to compile *nl_text* via the ``ipfs_datasets_py.logic`` module.

    Uses :class:`~ipfs_datasets_py.logic.deontic.converter.DeonticConverter`
    when available. Returns ``None`` if the logic module is absent, the
    compilation fails, or produces no usable clauses.

    Args:
        nl_text: Raw natural-language policy text.

    Returns:
        A list of :class:`~temporal_policy.PolicyClause` objects, or ``None``.
    """
    try:
        import anyio  # required for DeonticConverter.convert_async
        from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    except ImportError:
        return None

    try:
        converter = DeonticConverter(
            use_cache=False,
            use_ml=False,
            enable_monitoring=False,
            jurisdiction="general",
            document_type="policy",
        )

        # Run the async converter synchronously using anyio's event-loop runner
        async def _run() -> Any:
            return await converter.convert_async(nl_text)

        result = anyio.run(_run)

        if not result.success:
            return None

        formula = result.output
        operator_str = str(formula.operator).upper()
        actor = formula.agent.name if formula.agent else "*"
        action = formula.proposition or "*"

        if "OBLIGATION" in operator_str:
            clause_type = "obligation"
        elif "PROHIBITION" in operator_str:
            clause_type = "prohibition"
        else:
            clause_type = "permission"

        return [PolicyClause(clause_type=clause_type, actor=actor, action=action)]

    except Exception as exc:  # pragma: no cover
        logger.debug("Logic module compile failed (%s); falling back to regex", exc)
        return None


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

class NLUCANPolicyCompiler:
    """Compiles natural-language policy strings into UCAN-aligned PolicyObjects.

    The compiler is **stateless** — it does not store compiled policies itself.
    Storing and retrieving compiled policies is the responsibility of
    :class:`UCANPolicyGate` or :class:`PolicyRegistry`.

    Compilation strategy:

    1. Try the ``ipfs_datasets_py.logic`` deontic converter (full NLP).
    2. Fall back to the built-in regex-based heuristic parser.
    3. If neither produces any clauses, return an open-to-all permission policy
       (opt-in, non-restrictive default).

    Args:
        use_logic_module: Whether to attempt the logic-module path (default
            ``True``).  Disable in tests or restricted environments.
        version: Version tag stored in produced :class:`CompiledUCANPolicy`
            objects.
    """

    def __init__(
        self,
        *,
        use_logic_module: bool = True,
        version: str = "v1",
    ) -> None:
        self._use_logic_module = use_logic_module
        self._version = version

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, nl_policy: str, *, description: str = "") -> CompiledUCANPolicy:
        """Compile *nl_policy* into a :class:`CompiledUCANPolicy`.

        If the source text cannot be parsed into any meaningful clauses, the
        compiler emits a **warning** and returns a wildcard-permission policy
        so that the system remains open by default.

        Args:
            nl_policy: Raw natural-language policy string.
            description: Optional human-readable label stored in the
                :class:`PolicyObject`.

        Returns:
            A :class:`CompiledUCANPolicy` ready for registration with a gate.
        """
        if not nl_policy or not nl_policy.strip():
            raise ValueError("nl_policy must be a non-empty string")

        source_hash = _sha256_text(nl_policy)
        clauses = self._compile_to_clauses(nl_policy)

        if not clauses:
            warnings.warn(
                "NL policy could not be parsed into any clauses; "
                "defaulting to open-access (wildcard permission). "
                "Register a more explicit policy to restrict access.",
                RuntimeWarning,
                stacklevel=2,
            )
            clauses = [PolicyClause(clause_type="permission", actor="*", action="*")]

        policy = PolicyObject(
            clauses=clauses,
            description=description or nl_policy[:120],
        )

        return CompiledUCANPolicy(
            policy=policy,
            source_hash=source_hash,
            compiler_version=self._version,
            metadata={
                "clause_count": len(clauses),
                "strategy": "logic_module" if self._use_logic_module else "regex",
            },
        )

    def recompile_if_stale(
        self,
        source: NLPolicySource,
        compiled: CompiledUCANPolicy,
    ) -> Tuple[CompiledUCANPolicy, bool]:
        """Return *(policy, was_recompiled)* after checking hash freshness.

        Compares the SHA-256 hash stored in *compiled* against the live hash
        of *source*.  If they differ, recompiles *source.text* and returns the
        fresh :class:`CompiledUCANPolicy` with ``was_recompiled=True``.

        Args:
            source: The :class:`NLPolicySource` that produced *compiled*.
            compiled: The previously compiled policy.

        Returns:
            A ``(CompiledUCANPolicy, bool)`` tuple.
        """
        if source.source_hash == compiled.source_hash:
            return compiled, False

        logger.info(
            "Policy source hash mismatch — recompiling. "
            "old=%s new=%s",
            compiled.source_hash[:12],
            source.source_hash[:12],
        )
        fresh = self.compile(source.text, description=compiled.policy.description)
        return fresh, True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compile_to_clauses(self, nl_text: str) -> List[PolicyClause]:
        """Run the compilation pipeline and return deontic clauses."""
        if self._use_logic_module:
            result = _try_logic_module_compile(nl_text)
            if result is not None:
                return result

        return _fallback_parse_nl_policy(nl_text)


# ---------------------------------------------------------------------------
# Policy registry (multi-policy store)
# ---------------------------------------------------------------------------

class PolicyRegistry:
    """Stores named NL policies and their compiled counterparts.

    Designed as a singleton-accessible global registry (see
    :func:`get_policy_registry`) as well as an injectable dependency.

    This class is **opt-in**: the registry starts empty and every intent is
    allowed until the user registers at least one policy.

    Args:
        compiler: The :class:`NLUCANPolicyCompiler` to use for (re-)compilation.
            Defaults to a new instance with default settings.
    """

    def __init__(self, compiler: Optional[NLUCANPolicyCompiler] = None) -> None:
        self._compiler = compiler or NLUCANPolicyCompiler()
        self._sources: Dict[str, NLPolicySource] = {}
        self._compiled: Dict[str, CompiledUCANPolicy] = {}

    # ------------------------------------------------------------------

    def register(self, name: str, nl_policy: str, *, description: str = "") -> CompiledUCANPolicy:
        """Register (or replace) a named NL policy and compile it.

        Args:
            name: Unique policy name (e.g. ``"admin_only"``).
            nl_policy: Raw NL policy string.
            description: Optional label for the compiled :class:`PolicyObject`.

        Returns:
            The freshly compiled :class:`CompiledUCANPolicy`.
        """
        source = NLPolicySource(text=nl_policy)
        compiled = self._compiler.compile(nl_policy, description=description)
        self._sources[name] = source
        self._compiled[name] = compiled
        logger.debug("Registered policy %r (%d clauses)", name, len(compiled.policy.clauses))
        return compiled

    def get(self, name: str) -> Optional[CompiledUCANPolicy]:
        """Return the compiled policy for *name*, recompiling if stale.

        Returns ``None`` when *name* is not registered.

        Args:
            name: Policy name.

        Returns:
            The (possibly freshly recompiled) :class:`CompiledUCANPolicy`, or
            ``None``.
        """
        if name not in self._compiled:
            return None
        source = self._sources[name]
        compiled = self._compiled[name]
        fresh, was_recompiled = self._compiler.recompile_if_stale(source, compiled)
        if was_recompiled:
            self._compiled[name] = fresh
        return fresh

    def remove(self, name: str) -> bool:
        """Remove a registered policy.

        Args:
            name: Policy name to remove.

        Returns:
            ``True`` if the policy existed and was removed; ``False`` otherwise.
        """
        existed = name in self._compiled
        self._sources.pop(name, None)
        self._compiled.pop(name, None)
        return existed

    def list_names(self) -> List[str]:
        """Return a list of all registered policy names."""
        return list(self._sources)

    def __len__(self) -> int:
        return len(self._sources)


# ---------------------------------------------------------------------------
# Global registry singleton
# ---------------------------------------------------------------------------

_GLOBAL_REGISTRY: Optional[PolicyRegistry] = None


def get_policy_registry() -> PolicyRegistry:
    """Return the process-global :class:`PolicyRegistry` (lazy-init).

    Returns:
        The singleton :class:`PolicyRegistry` instance.
    """
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = PolicyRegistry()
    return _GLOBAL_REGISTRY


# ---------------------------------------------------------------------------
# Policy Gate
# ---------------------------------------------------------------------------

class UCANPolicyGate:
    """Middleware that evaluates MCP tool intents through registered NL policies.

    Usage model
    -----------
    * **No registered policies** → every intent returns ``"allow"``
      (*open by default*).
    * **One or more policies registered** → intents are evaluated against all
      matching policies; the first ``"deny"`` wins.

    Args:
        compiler: :class:`NLUCANPolicyCompiler` used for on-demand recompilation.
        registry: An optional pre-populated :class:`PolicyRegistry`.  If ``None``,
            a fresh empty registry is created.
        evaluator: An optional :class:`~temporal_policy.PolicyEvaluator`.
    """

    def __init__(
        self,
        compiler: Optional[NLUCANPolicyCompiler] = None,
        *,
        registry: Optional[PolicyRegistry] = None,
        evaluator: Optional[PolicyEvaluator] = None,
    ) -> None:
        self._compiler = compiler or NLUCANPolicyCompiler()
        self._registry = registry or PolicyRegistry(self._compiler)
        self._evaluator = evaluator or PolicyEvaluator()

    # ------------------------------------------------------------------
    # Registration (opt-in)
    # ------------------------------------------------------------------

    def register_policy(
        self,
        name: str,
        nl_policy: str,
        *,
        description: str = "",
    ) -> CompiledUCANPolicy:
        """Register a named NL policy with this gate.

        Args:
            name: Unique policy name.
            nl_policy: Raw NL policy text.
            description: Optional description.

        Returns:
            The compiled :class:`CompiledUCANPolicy`.
        """
        return self._registry.register(name, nl_policy, description=description)

    def remove_policy(self, name: str) -> bool:
        """Remove a registered policy from this gate.

        Args:
            name: Policy name to remove.

        Returns:
            ``True`` if removed; ``False`` if not found.
        """
        return self._registry.remove(name)

    def list_policies(self) -> List[str]:
        """Return the names of all registered policies."""
        return self._registry.list_names()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        intent: IntentObject,
        *,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        policy_name: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> DecisionObject:
        """Evaluate *intent* against registered policies.

        This gate uses a **prohibition-first, open-world** evaluation model:

        * **No registered policies** → ``"allow"`` (open by default).
        * **At least one matching prohibition** → ``"deny"`` (the prohibition wins).
        * **No matching prohibition** → ``"allow"`` (open by default, even if no
          explicit permission clause covers the actor/tool).

        This model enforces the *opt-in* nature of the gate: registering a policy
        only restricts what is **explicitly prohibited**; everything else remains
        open.

        If *policy_name* is given, only that policy is evaluated.  Otherwise, all
        registered policies are evaluated; the first ``"deny"`` wins.

        Args:
            intent: The :class:`~cid_artifacts.IntentObject` to evaluate.
            actor: Optional actor DID / role identifier.
            resource: Optional resource scope.
            policy_name: If provided, evaluate only this named policy.
            now: Evaluation timestamp override.

        Returns:
            A :class:`~cid_artifacts.DecisionObject` with the verdict.
        """
        if not self._registry.list_names():
            return self._open_allow(intent)

        names = [policy_name] if policy_name else self._registry.list_names()
        eval_time = now or datetime.now(timezone.utc)
        effective_actor = actor or "*"

        for name in names:
            compiled = self._registry.get(name)
            if compiled is None:
                continue

            # Only check prohibition clauses — this gate is open-world for permissions.
            for clause in compiled.policy.clauses:
                if clause.clause_type != "prohibition":
                    continue
                from .temporal_policy import _clause_matches  # noqa: PLC0415
                if _clause_matches(clause, effective_actor, intent.tool, resource, eval_time):
                    return DecisionObject(
                        decision="deny",
                        intent_cid=intent.intent_cid,
                        policy_cid=compiled.policy.policy_cid,
                        proofs_checked=[compiled.policy.policy_cid],
                        justification=(
                            f"Prohibited by policy '{name}': "
                            f"actor={effective_actor} action={intent.tool}"
                        ),
                    )

        # No prohibition matched — open by default.
        return self._open_allow(intent)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _open_allow(intent: IntentObject) -> DecisionObject:
        """Build an ``"allow"`` decision representing the open-by-default gate."""
        return DecisionObject(
            decision="allow",
            intent_cid=intent.intent_cid,
            policy_cid="",
            proofs_checked=[],
            justification="No restricting policy registered (open by default)",
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def compile_nl_policy(
    nl_policy: str,
    *,
    description: str = "",
    use_logic_module: bool = True,
) -> CompiledUCANPolicy:
    """One-shot helper: compile *nl_policy* and return a :class:`CompiledUCANPolicy`.

    Args:
        nl_policy: Raw NL policy string.
        description: Optional policy description.
        use_logic_module: Whether to try the logic module first.

    Returns:
        A :class:`CompiledUCANPolicy` ready for registration with a
        :class:`UCANPolicyGate`.

    Example::

        policy = compile_nl_policy(
            "Only admin may call admin_tools. "
            "All users may call read_tools."
        )
        gate = UCANPolicyGate()
        gate.register_policy("main", policy.policy.description)
    """
    compiler = NLUCANPolicyCompiler(use_logic_module=use_logic_module)
    return compiler.compile(nl_policy, description=description)
