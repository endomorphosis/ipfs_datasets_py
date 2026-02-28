"""
F-logic (Frame Logic / ErgoAI) tools for the MCP server and CLI.

Functions
---------
flogic_assert
    Assert F-logic frames and class definitions into the shared ontology.
flogic_query
    Execute an Ergo query against the current ontology, with caching.
flogic_check_consistency
    Check whether a set of KG triples is consistent with F-logic constraints.
flogic_normalize_term
    Resolve a term (or list of terms) to its canonical form via the
    SemanticNormalizer (SymAI when available, dictionary fallback otherwise).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — the flogic module is optional
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.logic.flogic.flogic_proof_cache import (
        CachedErgoAIWrapper,
        get_global_cached_wrapper,
    )
    from ipfs_datasets_py.logic.flogic.flogic_types import (
        FLogicClass,
        FLogicFrame,
        FLogicStatus,
    )
    _FLOGIC_AVAILABLE = True
except Exception as _flogic_err:
    logger.warning("F-logic module not available: %s", _flogic_err)
    _FLOGIC_AVAILABLE = False


def _unavailable(tool: str) -> Dict[str, Any]:
    return {"success": False, "error": f"{tool}: F-logic module not available."}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def flogic_assert(
    frames: Optional[List[Dict[str, Any]]] = None,
    classes: Optional[List[Dict[str, Any]]] = None,
    rules: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Assert F-logic frames and class definitions into the shared ontology.

    Frames and classes are accumulated in the process-wide
    :class:`~ipfs_datasets_py.logic.flogic.flogic_proof_cache.CachedErgoAIWrapper`
    singleton.  Adding new facts automatically invalidates the proof cache
    for any goal whose cache key depends on the changed ontology.

    Args:
        frames: List of frame dicts, each with keys:
            ``object_id`` (str, required),
            ``scalar_methods`` (dict, optional),
            ``set_methods`` (dict, optional),
            ``isa`` (str, optional).
        classes: List of class dicts, each with keys:
            ``class_id`` (str, required),
            ``superclasses`` (list[str], optional),
            ``signature_methods`` (dict[str, str], optional).
        rules: Raw Ergo rule strings to add (max 50).

    Returns:
        Dict with ``success`` (bool), ``frames_added``, ``classes_added``,
        ``rules_added``, and ``program_snippet`` (first 400 chars of the
        rendered ontology program).
    """
    if not _FLOGIC_AVAILABLE:
        return _unavailable("flogic_assert")

    ergo = get_global_cached_wrapper()
    frames_added = classes_added = rules_added = 0

    for f in (frames or [])[:200]:
        try:
            ergo.add_frame(
                FLogicFrame(
                    object_id=str(f["object_id"]),
                    scalar_methods=dict(f.get("scalar_methods") or {}),
                    set_methods={k: list(v) for k, v in (f.get("set_methods") or {}).items()},
                    isa=f.get("isa"),
                )
            )
            frames_added += 1
        except Exception as exc:
            logger.warning("flogic_assert: bad frame %s: %s", f, exc)

    for c in (classes or [])[:200]:
        try:
            ergo.add_class(
                FLogicClass(
                    class_id=str(c["class_id"]),
                    superclasses=list(c.get("superclasses") or []),
                    signature_methods=dict(c.get("signature_methods") or {}),
                )
            )
            classes_added += 1
        except Exception as exc:
            logger.warning("flogic_assert: bad class %s: %s", c, exc)

    for rule in (rules or [])[:50]:
        if rule and isinstance(rule, str):
            ergo.add_rule(rule)
            rules_added += 1

    prog = ergo.get_program()
    return {
        "success": True,
        "frames_added": frames_added,
        "classes_added": classes_added,
        "rules_added": rules_added,
        "program_snippet": prog[:400],
        "total_frames": len(ergo.ontology.frames),
        "total_classes": len(ergo.ontology.classes),
        "total_rules": len(ergo.ontology.rules),
        "simulation_mode": ergo.simulation_mode,
    }


async def flogic_query(
    goal: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Execute an Ergo query against the current F-logic ontology.

    Identical queries (same goal **and** same ontology program) are served
    from the proof cache without re-running the prover.

    Args:
        goal: Ergo query goal, e.g. ``"?X : Dog"`` or
              ``"?X[name -> ?N] : Person"``.
        use_cache: Whether to consult the proof cache (default ``True``).

    Returns:
        Dict with ``success`` (bool), ``status`` (str), ``bindings`` (list),
        ``from_cache`` (bool), ``execution_time_ms`` (float),
        ``simulation_mode`` (bool).
    """
    if not _FLOGIC_AVAILABLE:
        return _unavailable("flogic_query")
    if not goal or not isinstance(goal, str):
        return {"success": False, "error": "'goal' must be a non-empty string.", "bindings": []}

    ergo = get_global_cached_wrapper()
    if not use_cache:
        ergo.enable_caching = False

    result = ergo.query(goal)

    return {
        "success": True,
        "status": result.status.value,
        "bindings": result.bindings,
        "from_cache": result.from_cache,
        "execution_time_ms": result.execution_time * 1000,
        "simulation_mode": ergo.simulation_mode,
        "error_message": result.error_message,
    }


async def flogic_check_consistency(
    kg_triples: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Check whether a set of knowledge-graph triples is consistent with
    the current F-logic ontology.

    Each triple is converted to an :class:`~ipfs_datasets_py.logic.flogic.flogic_types.FLogicFrame`
    and asserted into the ontology.  The consistency check queries for any
    structural violations (e.g. blank predicates, duplicate scalar values).

    Args:
        kg_triples: List of ``{"subject": …, "predicate": …, "object": …}``
            dicts (max 500).

    Returns:
        Dict with ``success`` (bool), ``consistent`` (bool),
        ``violations`` (list of dicts), ``frames_checked`` (int).
    """
    if not _FLOGIC_AVAILABLE:
        return _unavailable("flogic_check_consistency")
    if not kg_triples:
        return {"success": True, "consistent": True, "violations": [], "frames_checked": 0}

    # Load flogic_optimizer directly to avoid the pre-existing broken
    # optimizers/common/__init__.py import chain (requires anyio).
    # TODO: remove this workaround once ipfs_datasets_py/optimizers/common/
    #       performance.py no longer has an unconditional `import anyio` at
    #       module level (tracked separately).
    import importlib.util as _ilu
    import sys as _sys
    _mod_name = "ipfs_datasets_py.optimizers.logic.flogic_optimizer"
    if _mod_name not in _sys.modules:
        import pathlib as _pl
        _path = (
            _pl.Path(__file__).resolve().parents[4]
            / "ipfs_datasets_py"
            / "optimizers"
            / "logic"
            / "flogic_optimizer.py"
        )
        _spec = _ilu.spec_from_file_location(_mod_name, _path)
        _mod = _ilu.module_from_spec(_spec)
        _sys.modules[_mod_name] = _mod
        _spec.loader.exec_module(_mod)
    FLogicSemanticOptimizer = _sys.modules[_mod_name].FLogicSemanticOptimizer

    optimizer = FLogicSemanticOptimizer()
    violations_raw = optimizer._check_flogic_consistency(list(kg_triples[:500]))

    violations = [
        {
            "frame_id": v.frame_id,
            "constraint": v.constraint,
            "details": v.details,
        }
        for v in violations_raw
    ]

    return {
        "success": True,
        "consistent": len(violations) == 0,
        "violations": violations,
        "frames_checked": len({t.get("subject", "") for t in kg_triples}),
    }


__all__ = [
    "flogic_assert",
    "flogic_query",
    "flogic_check_consistency",
    "flogic_normalize_term",
]


async def flogic_normalize_term(
    terms: List[str],
    normalize_goals: bool = False,
) -> Dict[str, Any]:
    """
    Resolve terms or query goals to their canonical semantic forms.

    Uses the :class:`~ipfs_datasets_py.logic.flogic.semantic_normalizer.SemanticNormalizer`
    (SymAI-powered when available, falling back to a built-in synonym map).
    The result can be used to pre-canonicalize queries before caching so
    that semantic synonyms (e.g. ``"canine"`` and ``"dog"``) share the
    same proof-cache entry.

    Args:
        terms: List of term strings or full Ergo goal strings (max 200).
        normalize_goals: When ``True``, treat each entry as a full Ergo
            query goal and apply goal-level normalization (identifiers
            replaced in-place); when ``False``, normalize each entry as
            a single identifier.

    Returns:
        Dict with ``success`` (bool), ``normalized`` (list of
        ``{"input": …, "canonical": …, "changed": bool}`` dicts),
        ``symai_active`` (bool).
    """
    if not _FLOGIC_AVAILABLE:
        return _unavailable("flogic_normalize_term")
    if not terms:
        return {"success": True, "normalized": [], "symai_active": False}

    try:
        from ipfs_datasets_py.logic.flogic.semantic_normalizer import (
            SemanticNormalizer,
            get_global_normalizer,
            _SYMAI_AVAILABLE,
        )
        norm = get_global_normalizer()
    except Exception as exc:
        logger.warning("SemanticNormalizer unavailable: %s", exc)
        return {"success": False, "error": str(exc), "normalized": []}

    results = []
    for t in terms[:200]:
        if not isinstance(t, str):
            continue
        if normalize_goals:
            canonical = norm.normalize_goal(t)
        else:
            canonical = norm.normalize_term(t)
        results.append({
            "input": t,
            "canonical": canonical,
            "changed": canonical != t,
        })

    return {
        "success": True,
        "normalized": results,
        "symai_active": norm.symai_available,
    }
