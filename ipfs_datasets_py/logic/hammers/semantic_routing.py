"""Family-aware entry point above the raw Hammer solver transport.

Provider declarations describe possible capabilities, not faithful translations.
This owner intersects them with a small executable lowering profile and checks
the actual native AST before constructing any attempt. Unsupported operators or
families never become uninterpreted Boolean atoms. The initial profile is exact
binder-free propositional logic only; richer families keep their native owners.

``SolverPortfolio`` remains a low-level typed-translation transport. Callers
with family-tagged native projections should use this checked entry point.
Neither a permitted route nor a solver verdict grants source fidelity or Lean
admission. SMT assertion satisfiability and ATP conjecture validity are separate
operations and are never combined into one success vote.
"""
from __future__ import annotations

from functools import reduce
import hashlib
import json
import math
from pathlib import Path

from . import models, policy, portfolio, translation
from ..families import models as family_models, providers
from ..parsers import modal

SCHEMA = "family-checked-solver-routing/v1"
PROFILE = "shared-logic/binder-free-propositional/v1"
MAX_TEXT_BYTES = 65536
MAX_AST_NODES = 4096
MAX_DEPTH = 64
_MODULES = (models, policy, portfolio, translation, family_models, providers, modal)
_PINS = {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
         for module in _MODULES}
_PINS[str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _guard():
    for path, expected in _PINS.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError("semantic routing producer changed after import")


def _propositional_term(node, depth=0, budget=None):
    """Translate explicit Boolean nodes without erasing semantic operators."""
    budget = [MAX_AST_NODES] if budget is None else budget
    budget[0] -= 1
    if type(node) is not dict or depth > MAX_DEPTH or budget[0] < 0 or node.get("binders"):
        raise ValueError("bounded binder-free propositional AST required")
    kind, arguments = node.get("kind"), node.get("arguments")
    if type(arguments) is not list:
        raise ValueError("native propositional arguments must be a list")
    if kind == "predicate" and not arguments:
        return translation.Const(node["symbol"], translation.PROP_SORT)
    if kind in ("true", "false") and not arguments:
        return translation.BoolLit(kind == "true")
    # Reject the operator before descending: a modal/deontic wrapper must never
    # be silently removed even when its body happens to be propositional.
    if kind not in ("not", "and", "or", "implies", "iff"):
        raise ValueError("unsupported native propositional operator: " + str(kind))
    children = [_propositional_term(child, depth + 1, budget) for child in arguments]
    if kind == "not" and len(children) == 1:
        return translation.Not(children[0])
    if kind in ("and", "or") and len(children) >= 2:
        return reduce(translation.And if kind == "and" else translation.Or, children)
    if kind in ("implies", "iff") and len(children) == 2:
        return (translation.Implies if kind == "implies" else translation.Iff)(*children)
    raise ValueError("unsupported native propositional operator arity: " + str(kind))


def _capability(solver_name):
    spec = policy.solver_spec(solver_name)
    smt = spec.target is models.TranslationTarget.SMTLIB
    family = "propositional" if smt else "first_order"
    operation = "check_satisfiability" if smt else "prove"
    property_id = "satisfiability" if smt else "validity"
    entry = providers.BASELINE_PROVIDER_CATALOG.get("eprover" if solver_name == "e" else solver_name)
    supports = [support for support in entry.family_support
                if support.family_id == family
                and support.support_level is family_models.SupportLevel.NATIVE
                and "propositional" in support.fragment_ids
                and operation in support.operation_ids
                and property_id in support.property_ids]
    if len(supports) != 1:
        raise ValueError("provider catalog lacks exact native propositional operation capability: " + solver_name)
    return spec, {"solver_name": solver_name, "provider_id": entry.provider_id,
        "provider_version": entry.provider_version,
        "catalog_schema": providers.BASELINE_PROVIDER_CATALOG.schema_version,
        "capability_sha256": hashlib.sha256(_raw(entry.to_dict())).hexdigest(),
        "declared_support": supports[0].to_dict(), "source_logic_family": "propositional",
        "lowering_profile": PROFILE, "target_format": spec.target.value,
        "operation": operation, "property": property_id,
        "input_semantics": "assert_formula" if smt else "conjecture_formula",
        "verdict_semantics": "formula_satisfiability" if smt else "formula_validity_candidate",
        "embedding": "identity_propositional" if smt else "zero_arity_predicates_in_classical_first_order",
        "source_semantics_verified": False, "admitted": False, "qualified": False}


def prepare_family_portfolio(*, request_id, source_construct, logic_family, ast_format,
                             printed, native_ast, solver_names):
    """Build exact supported attempts; no process, executable probe or lease.

    The original source/report binding belongs to the caller. This function
    proves only parser replay and membership in its closed translation profile.
    A declaration of DCEC/TDFOL provider support cannot bypass that profile.
    """
    _guard()
    if logic_family != "propositional" or ast_format != "shared_logic":
        raise ValueError("unsupported family/profile: exact native propositional targets only; no faithful lowering registered")
    for value in (request_id, source_construct):
        if type(value) is not str or not value or len(value.encode()) > 1024:
            raise ValueError("bounded request and source construct identifiers required")
    if type(printed) is not str or not printed or len(printed.encode()) > MAX_TEXT_BYTES:
        raise ValueError("bounded native formula text required")
    if type(solver_names) not in (tuple, list) or not 1 <= len(solver_names) <= 4:
        raise ValueError("one to four explicit solver names required")
    if any(type(name) is not str for name in solver_names) or len(set(solver_names)) != len(solver_names):
        raise ValueError("distinct explicit solver names required")
    # Walk first to bound supplied AST depth/nodes before comparisons or JSON.
    term = _propositional_term(native_ast)
    parsed = modal.parse_modal(printed, modal.profile_k())
    if not parsed.ok or parsed.diagnostics or parsed.root.to_dict() != native_ast:
        raise ValueError("diagnostic native AST differs from exact target parser replay")
    owner = translation.TranslationContext(request_id=request_id)
    attempts, routes = [], []
    for name in solver_names:
        spec, route = _capability(name)
        record = owner.translate(source_construct=source_construct, term=term, target=spec.target)
        if record.status is not models.TranslationStatus.SUPPORTED or record.obligations:
            raise ValueError("complete native propositional translation required")
        attempts.append(portfolio.PortfolioAttemptSpec(translation=record, solver_name=name))
        routes.append({**route, "translation": record.to_dict(), "runnable_fragment": True})
    receipt = {"schema": SCHEMA, "profile": PROFILE, "source_logic_family": logic_family,
        "native_ast_sha256": hashlib.sha256(_raw(native_ast)).hexdigest(),
        "printed_sha256": hashlib.sha256(printed.encode()).hexdigest(),
        "routes": routes, "producer": dict(_PINS), "source_semantics_verified": False,
        "admitted": False, "qualified": False, "cross_operation_vote_permitted": False}
    return attempts, receipt


def run_family_portfolio(*, expected_routing, run_policy, resource_scheduler=None,
                         resource_lane="hammer_lean", resource_wait_timeout_seconds=30,
                         parent_lease=None, cancel_event=None,
                         **target):
    """Replay family/AST/capability checks immediately before raw execution.

    Raw caller-supplied TranslationRecord objects are never accepted. A cached
    routing receipt is only an equality check, not an authority token.
    A native parent lease supplies its scheduler when omitted. Serialized
    parent tokens require an explicitly supplied matching scheduler: a token
    does not carry scheduler configuration. Neither form falls back to a new
    root reservation. Cancellation reaches resource waits and native children.
    """
    if parent_lease is not None:
        if isinstance(parent_lease, portfolio.ResourceLease):
            owner = parent_lease._scheduler
            if resource_scheduler is not None and resource_scheduler is not owner:
                raise ValueError("parent lease requires its owning resource scheduler")
            resource_scheduler = owner
        elif isinstance(parent_lease, portfolio.ResourceLeaseToken):
            if not isinstance(resource_scheduler, portfolio.GlobalResourceScheduler):
                raise ValueError("parent token requires an explicit resource scheduler")
            if Path(parent_lease.state_path).resolve() != resource_scheduler.state_path:
                raise ValueError("parent token belongs to another resource scheduler")
        else:
            raise ValueError("parent_lease must be a native ResourceLease or ResourceLeaseToken")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise ValueError("cancel_event must provide is_set")
    if resource_wait_timeout_seconds is not None and (
            type(resource_wait_timeout_seconds) not in (int, float)
            or not math.isfinite(resource_wait_timeout_seconds) or resource_wait_timeout_seconds < 0):
        raise ValueError("resource wait timeout must be finite and non-negative")
    attempts, routing = prepare_family_portfolio(**target)
    if _raw(routing) != _raw(expected_routing):
        raise ValueError("semantic routing changed before execution")
    if run_policy.cancel_on_first_conclusive and len({r["operation"] for r in routing["routes"]}) != 1:
        raise ValueError("mixed solver operations cannot cancel one another as conclusive")
    runner = portfolio.SolverPortfolio(run_policy, resource_scheduler=resource_scheduler,
        resource_lane=resource_lane, resource_wait_timeout_seconds=resource_wait_timeout_seconds)
    result = runner.run(target["request_id"], attempts, parent_lease=parent_lease, cancel_event=cancel_event)
    _guard()
    return result


__all__ = ["SCHEMA", "PROFILE", "prepare_family_portfolio", "run_family_portfolio"]
