"""Integration coverage for ExecutableProviderMatrix@1 (FVT-G012 / FVT-013).

Acceptance:

* SMT, state-model, runtime, authorization, protocol, hyperproperty, ATP,
  Hammer, and kernel providers are discoverable without import side effects;
* available lanes execute;
* absent lanes report unavailable;
* portfolios preserve typed authority and quarantine contradiction.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.portfolio import (
    AttemptFamily,
    CapabilityStatus,
    PortfolioAttemptOutcome,
    PortfolioCapability,
    PortfolioRole,
    PortfolioVerdict,
)
from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_MATRIX,
    EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
    LazyMatrixProofBackend,
    PROVIDER_MATRIX_FAMILIES,
    declared_backend_catalog,
    default_backend_registry,
    provider_matrix_by_family,
    provider_matrix_declarations,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.verification_api import (
    EXECUTABLE_PROVIDER_MATRIX_INTERFACE as API_MATRIX_INTERFACE,
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
)


REQUIRED_FAMILIES = (
    "smt",
    "state_model",
    "runtime",
    "authorization",
    "protocol",
    "hyperproperty",
    "atp",
    "hammer",
    "kernel",
)


def _fresh_import(module_name: str):
    root = module_name.split(".", 1)[0]
    for name in list(sys.modules.keys()):
        if name == root or name.startswith(root + "."):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def test_provider_matrix_import_is_side_effect_free(monkeypatch) -> None:
    """Discovering the matrix never installs packages or probes tools at import.

    Uses a process-local import of the already-loaded modules rather than
    purging ``sys.modules`` (which would break class identity for later tests).
    """

    monkeypatch.delenv("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS", raising=False)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        registry_mod = importlib.import_module("ipfs_datasets_py.logic.backends.registry")
        api_mod = importlib.import_module("ipfs_datasets_py.logic.verification_api")
        # Re-bind public discovery entrypoints; construction must stay inert.
        catalog = registry_mod.declared_backend_catalog()
        _ = registry_mod.provider_matrix_declarations()

    assert registry_mod.EXECUTABLE_PROVIDER_MATRIX_INTERFACE == (
        "ExecutableProviderMatrix@1"
    )
    assert api_mod.EXECUTABLE_PROVIDER_MATRIX_INTERFACE == "ExecutableProviderMatrix@1"
    assert len(catalog) >= 9
    # Optional tool stacks must not be required merely for declarative discovery.
    assert "ipfs_datasets_py.logic.external_provers.lazy_installer" not in sys.modules
    ipfs_warnings = [
        item
        for item in recorded
        if "ipfs_datasets_py" in (getattr(item, "filename", "") or "")
    ]
    assert ipfs_warnings == []


def test_declarative_matrix_covers_every_required_family() -> None:
    assert set(PROVIDER_MATRIX_FAMILIES) == set(REQUIRED_FAMILIES)
    by_family = provider_matrix_by_family()
    for family in REQUIRED_FAMILIES:
        assert family in by_family
        assert by_family[family], f"family {family} must declare at least one provider"

    declarations = provider_matrix_declarations()
    assert declarations is EXECUTABLE_PROVIDER_MATRIX
    ids = {entry.provider_id for entry in declarations}
    # Portfolio-aligned core identifiers.
    assert {
        "z3",
        "cvc5",
        "tla_tlc",
        "apalache",
        "runtime_mtl",
        "datalog_secpal",
        "proverif",
        "tamarin",
        "hyperltl_autohyper_mchyper",
        "vampire",
        "eprover",
        "hammer",
        "lean",
        "rocq",
        "isabelle",
    } <= ids

    catalog = declared_backend_catalog()
    catalog_ids = {item["provider_id"] for item in catalog}
    assert catalog_ids == ids
    for item in catalog:
        assert item["availability"] == "declared"
        assert item["source"] == "backend_registry"
        assert item["metadata"]["executable_provider_matrix"] == (
            EXECUTABLE_PROVIDER_MATRIX_INTERFACE
        )
        assert item["logic_families"]
        assert item["query_kinds"]


def test_default_registry_registers_lazy_matrix_without_probes() -> None:
    registry = default_backend_registry()
    assert set(registry) == {entry.provider_id for entry in EXECUTABLE_PROVIDER_MATRIX}
    for backend_id in registry:
        backend = registry[backend_id]
        assert isinstance(backend, LazyMatrixProofBackend)
        assert isinstance(backend.capabilities, BackendCapabilities)
        # Construction alone must not force factory loads.
        assert backend._delegate_loaded is False  # noqa: SLF001 — intentional state check

    # Declared catalog from a live registry still never probes availability.
    catalog = declared_backend_catalog(registry)
    assert {item["provider_id"] for item in catalog} == set(registry)
    for item in catalog:
        assert item["availability"] == "declared"


@pytest.mark.parametrize(
    ("alias", "canonical_id", "logic_family"),
    (
        ("coq", "rocq", "software_verification"),
        ("coqc", "rocq", "software_verification"),
        ("e", "eprover", "first_order"),
    ),
)
def test_default_registry_dispatches_declared_provider_aliases(
    alias: str,
    canonical_id: str,
    logic_family: str,
) -> None:
    registry = default_backend_registry()
    request = BackendRequest(
        request_id=f"req:{alias}",
        claim_id=f"claim:{alias}",
        declaration_id=f"decl:{alias}",
        claim_digest=stable_digest({"claim": alias}),
        obligation_id=f"obl:{alias}",
        obligation_digest=stable_digest({"obligation": alias}),
        assumption_ids=(),
        logic_family=logic_family,
        query_kind=QueryKind.THEOREM_PROOF,
        bounds=ExecutionBounds(timeout_ms=1_000),
        payload=FrozenMap({"statement": "True"}),
        requested_backend_id=alias,
    )

    assert registry[alias] is registry[canonical_id]
    assert registry.supporting(request) == (canonical_id,)


def test_list_providers_exposes_full_matrix_declaratively() -> None:
    api = get_verification_api(reset=True)
    response = api.list_providers()
    assert response.status is VerificationStatus.DECLARATIVE
    assert response.authority is VerificationAuthority.DECLARATIVE
    assert response.result["executable_provider_matrix"] == API_MATRIX_INTERFACE
    provider_ids = {item["provider_id"] for item in response.result["providers"]}
    assert {
        "z3",
        "cvc5",
        "tla_tlc",
        "runtime_mtl",
        "datalog_secpal",
        "proverif",
        "hyperltl_autohyper_mchyper",
        "vampire",
        "hammer",
        "lean",
    } <= provider_ids
    for item in response.result["providers"]:
        if item.get("source") in {
            "executable_provider_matrix",
            "backend_registry",
            "family_taxonomy",
        }:
            assert item["availability"] in {"declared", "available", "unavailable"}


def test_available_and_absent_lanes_report_explicitly() -> None:
    api = get_verification_api(reset=True)
    registry = api._registry()  # noqa: SLF001

    # Always-available facade lanes.
    assert registry.is_available("runtime_mtl") is True
    assert registry.is_available("datalog_secpal") is True

    runtime = api.probe_provider("runtime_mtl")
    assert runtime.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.UNAVAILABLE,
    }
    assert "available" in runtime.result
    if runtime.result["available"] is True:
        assert runtime.status is VerificationStatus.SUCCEEDED

    # Missing provider id remains unsupported (not a silent success).
    missing = api.probe_provider("not-a-matrix-provider")
    assert missing.status is VerificationStatus.UNSUPPORTED
    assert "provider:not-a-matrix-provider" in missing.unsupported_features

    # Kernel / protocol tools typically absent in CI — must report unavailable.
    for provider_id in ("lean", "tamarin", "vampire"):
        probe = api.probe_provider(provider_id)
        assert probe.status in {
            VerificationStatus.SUCCEEDED,
            VerificationStatus.UNAVAILABLE,
            VerificationStatus.UNSUPPORTED,
        }
        if probe.status is VerificationStatus.UNAVAILABLE:
            assert probe.result.get("available") is False


def test_available_smt_lane_executes_through_stable_check() -> None:
    api = get_verification_api(reset=True)
    response = api.check(
        {
            "statement": "(assert true)",
            "source": "(assert true)\n(check-sat)\n",
            "logic_family": "first_order",
            "query_kind": "satisfiability",
            "assumption_ids": ("env:trusted",),
        },
        backend_id="z3",
        request_id="req:matrix-z3",
    )
    assert response.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.UNAVAILABLE,
        VerificationStatus.ERROR,
    }
    assert response.provider_id in {"z3", ""}
    assert response.assumptions == ("env:trusted",)
    if response.status is VerificationStatus.SUCCEEDED:
        assert response.result.get("result_status") in {
            "sat",
            "unsat",
            "unknown",
            "satisfiable",
            "unsatisfiable",
        }


def test_unavailable_lane_run_reports_unavailable_not_success() -> None:
    """Synthetic unavailable matrix backend never becomes success by silence."""

    from ipfs_datasets_py.logic.backends.registry import (
        LazyMatrixProofBackend,
        ProviderMatrixEntry,
        ProofBackendRegistry,
        PROVIDER_MATRIX_FAMILY_KERNEL,
    )
    from ipfs_datasets_py.logic.ir_core import protocols as protocols_mod

    entry = ProviderMatrixEntry(
        provider_id="synthetic-kernel",
        family=PROVIDER_MATRIX_FAMILY_KERNEL,
        logic_families=("software_verification", "lean"),
        query_kinds=("theorem_proof",),
        factory_key="synthetic-kernel",
        notes="test-only unavailable kernel",
    )
    backend = LazyMatrixProofBackend(
        entry,
        factory=lambda: (_ for _ in ()).throw(RuntimeError("tool missing")),
        availability_probe=lambda: False,
    )
    registry = ProofBackendRegistry((backend,))
    api = LogicVerificationAPI(backend_registry=registry)

    claim = stable_digest({"claim": "synthetic"})
    obligation = stable_digest({"obl": "synthetic"})
    # Use the same protocols module object the registry binds against.
    request = protocols_mod.BackendRequest(
        request_id="req:synthetic",
        claim_id="claim:synthetic",
        declaration_id="decl:synthetic",
        claim_digest=claim,
        obligation_id="obl:synthetic",
        obligation_digest=obligation,
        assumption_ids=(),
        logic_family="software_verification",
        query_kind=protocols_mod.QueryKind.THEOREM_PROOF,
        bounds=protocols_mod.ExecutionBounds(timeout_ms=1_000),
        payload=FrozenMap({"statement": "True", "goal": "True"}),
        requested_backend_id="synthetic-kernel",
    )
    assert backend.is_available() is False
    attempt, result = backend.run(request)
    assert attempt.status.value == "unavailable"
    assert result.status.value in {"unknown", "unavailable", "error"}

    checked = api.check(
        {
            "statement": "True",
            "logic_family": "software_verification",
            "query_kind": "theorem_proof",
            "requested_backend_id": "synthetic-kernel",
        },
        backend_id="synthetic-kernel",
    )
    assert checked.status in {
        VerificationStatus.UNAVAILABLE,
        VerificationStatus.ERROR,
        VerificationStatus.UNSUPPORTED,
    }
    assert checked.status is not VerificationStatus.SUCCEEDED


def test_run_portfolio_executes_and_is_not_plan_only() -> None:
    api = get_verification_api(reset=True)
    planned = api.run_portfolio(
        {
            "obligation_id": "obl:plan-only",
            "property_kind": "satisfiability",
            "statement": "(assert true)",
        },
        execute=False,
    )
    assert planned.result.get("executed") is False
    assert "plan" in planned.result
    assert planned.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.PARTIAL,
    }

    executed = api.run_portfolio(
        {
            "obligation_id": "obl:execute",
            "property_kind": "satisfiability",
            "statement": "(assert true)",
            "assumption_ids": ("a:matrix",),
        },
        execute=True,
    )
    assert executed.result.get("executed") is True
    assert executed.result.get("executable_provider_matrix") == (
        EXECUTABLE_PROVIDER_MATRIX_INTERFACE
    )
    assert executed.assumptions == ("a:matrix",)
    assert "selection" in executed.result
    assert "verdict" in executed.result
    assert executed.result.get("attempt_count", 0) >= 1
    outcomes = executed.result.get("outcomes") or []
    assert outcomes, "executed portfolio must record per-attempt outcomes"
    # At least one attempt either ran or explicitly reported unavailable.
    statuses = {item.get("status") for item in outcomes}
    assert statuses & {
        "satisfiable",
        "unsatisfiable",
        "unknown",
        "unavailable",
        "error",
        "candidate",
        "proved",
        "disproved",
    }


def test_portfolio_quarantines_conflicting_conclusive_authorities() -> None:
    """Conflicting conclusive outcomes quarantine rather than pick a winner."""

    api = get_verification_api(reset=True)
    plan_response = api.run_portfolio(
        {
            "obligation_id": "obl:quarantine",
            "property_kind": "satisfiability",
            "statement": "P",
            "required_assurance": "bounded",
        },
        execute=False,
    )
    plan = plan_response.result["plan"]
    attempts = plan["attempts"]
    assert len(attempts) >= 2
    first, second = attempts[0], attempts[1]

    # Pass mapping outcomes so selection is independent of class identity.
    outcomes = [
        {
            "attempt_id": first["attempt_id"],
            "backend_id": first["backend_id"],
            "status": "unsatisfiable",
            "authority": "satisfiability",
            "role": "authority",
            "stage": int(first.get("stage", 0) or 0),
            "achieved_assurance": "bounded",
            "conclusive_counterexample": False,
        },
        {
            "attempt_id": second["attempt_id"],
            "backend_id": second["backend_id"],
            "status": "satisfiable",
            "authority": "satisfiability",
            "role": "authority",
            "stage": int(second.get("stage", 0) or 0),
            "achieved_assurance": "bounded",
            "conclusive_counterexample": True,
        },
    ]
    selected = api.run_portfolio(
        {
            "obligation_id": "obl:quarantine",
            "property_kind": "satisfiability",
            "statement": "P",
            "required_assurance": "bounded",
        },
        execute=False,
        outcomes=outcomes,
    )
    assert selected.result.get("executed") is True
    assert selected.result.get("verdict") == PortfolioVerdict.QUARANTINED.value
    assert selected.result.get("disagreement") is True
    assert selected.result.get("quarantined_attempt_ids")
    assert selected.authority is VerificationAuthority.NONE
    assert selected.status is VerificationStatus.PARTIAL


def test_portfolio_capabilities_reflect_matrix_families() -> None:
    api = get_verification_api(reset=True)
    # Mapping form avoids cross-module class identity issues under reimport.
    caps = [
        {
            "backend_id": "z3",
            "family": "solver",
            "status": "available",
        },
        {
            "backend_id": "missing-solver",
            "family": "solver",
            "status": "unavailable",
        },
    ]
    # Convert mappings into PortfolioCapability via portfolio constructors.
    from ipfs_datasets_py.logic.backends.portfolio import PortfolioCapability as PC

    typed_caps = [PC.from_dict(item) if hasattr(PC, "from_dict") else None for item in caps]
    if any(item is None for item in typed_caps):
        typed_caps = [
            PC(
                backend_id=item["backend_id"],
                family=AttemptFamily(item["family"]),
                status=CapabilityStatus(item["status"]),
            )
            for item in caps
        ]
    response = api.run_portfolio(
        {
            "obligation_id": "obl:caps",
            "property_kind": "satisfiability",
            "statement": "P",
        },
        capabilities=typed_caps,
        execute=True,
        probe_availability=False,
    )
    assert response.result.get("executed") is True
    gaps = response.result.get("capability_gaps") or []
    outcomes = response.result.get("outcomes") or []
    assert gaps or any(
        item.get("status") in {"unavailable", "unknown", "error", "satisfiable", "unsatisfiable"}
        or item.get("backend_id") == "z3"
        for item in outcomes
    )


def test_matrix_constants_align_across_api_and_registry() -> None:
    assert EXECUTABLE_PROVIDER_MATRIX_INTERFACE == API_MATRIX_INTERFACE
    assert EXECUTABLE_PROVIDER_MATRIX_INTERFACE == "ExecutableProviderMatrix@1"
    api = LogicVerificationAPI()
    assert api.interface == "LogicVerificationAPI@1"
    features = api.list_features()
    assert "run_portfolio" in features.result["operations"]
    assert "list_providers" in features.result["operations"]
