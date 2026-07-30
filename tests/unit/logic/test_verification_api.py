"""Unit tests for the stable Python software-verification API (LFV-G070).

Acceptance coverage for ``LogicVerificationAPI@1``:

* import is quiet and free of optional tool probes;
* discovery is declarative;
* responses expose status, authority, assumptions, bounds, translations,
  witnesses, and cache provenance;
* absent / unsupported features are explicit;
* legacy ``logic.api`` exact exports remain green (validated separately).
"""

from __future__ import annotations

import importlib
import sys
import warnings
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.verification_api import (
    LOGIC_VERIFICATION_API_INTERFACE,
    STABLE_OPERATIONS,
    CacheProvenance,
    FeatureAvailability,
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationResponse,
    VerificationStatus,
    get_verification_api,
    list_stable_features,
)


def _fresh_import(module_name: str):
    root = module_name.split(".", 1)[0]
    for name in list(sys.modules.keys()):
        if name == root or name.startswith(root + "."):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def _ipfs_origin_warnings(recorded: list[warnings.WarningMessage]) -> list[warnings.WarningMessage]:
    return [
        warning
        for warning in recorded
        if "ipfs_datasets_py" in (getattr(warning, "filename", "") or "")
    ]


def test_verification_api_import_is_quiet_and_lightweight(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS", raising=False)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        module = _fresh_import("ipfs_datasets_py.logic.verification_api")

    assert _ipfs_origin_warnings(recorded) == []
    assert module.LOGIC_VERIFICATION_API_INTERFACE == "LogicVerificationAPI@1"
    # Discovery-facing import must not pull optional prover / installer stacks.
    assert "ipfs_datasets_py.logic.integration" not in sys.modules
    assert "ipfs_datasets_py.logic.external_provers.lazy_installer" not in sys.modules


def test_interface_constants_and_stable_operations() -> None:
    assert LOGIC_VERIFICATION_API_INTERFACE == "LogicVerificationAPI@1"
    for operation in (
        "list_logic_families",
        "list_providers",
        "provider_capabilities",
        "compile_verification_artifact",
        "check",
        "monitor",
        "run_portfolio",
        "explain_counterexample",
        "verify_receipt",
        "attest_receipt",
        "probe_provider",
        "install_provider",
    ):
        assert operation in STABLE_OPERATIONS

    features = {item.feature_id: item for item in list_stable_features()}
    assert features["list_logic_families"].availability is FeatureAvailability.DECLARED
    assert features["probe_provider"].requires_opt_in is True
    assert features["install_provider"].availability is FeatureAvailability.OPT_IN
    assert features["advise"].authority_ceiling is VerificationAuthority.ADVISORY


def test_response_envelope_is_immutable_and_serialisable() -> None:
    response = VerificationResponse(
        operation="list_providers",
        status=VerificationStatus.DECLARATIVE,
        authority=VerificationAuthority.DECLARATIVE,
        result={"count": 0},
        assumptions=("a1",),
        bounds={"timeout_ms": 1},
        translations=({"profile": "identity"},),
        witnesses=({"kind": "none"},),
        unsupported_features=(),
        diagnostics=(),
        cache=CacheProvenance(source="test"),
        request_id="req:1",
    )
    payload = response.to_dict()
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert payload["status"] == "declarative"
    assert payload["authority"] == "declarative"
    assert payload["assumptions"] == ["a1"]
    assert payload["bounds"] == {"timeout_ms": 1}
    assert payload["translations"] == [{"profile": "identity"}]
    assert payload["witnesses"] == [{"kind": "none"}]
    assert payload["cache"]["source"] == "test"
    assert isinstance(response.digest, str) and len(response.digest) == 64
    with pytest.raises(FrozenInstanceError):
        response.status = VerificationStatus.ERROR  # type: ignore[misc]


def test_list_logic_families_is_declarative() -> None:
    api = LogicVerificationAPI()
    response = api.list_logic_families()
    assert response.status is VerificationStatus.DECLARATIVE
    assert response.authority is VerificationAuthority.DECLARATIVE
    assert response.result["count"] >= 10
    family_ids = {item["family_id"] for item in response.result["families"]}
    assert {"first_order", "temporal", "program", "authorization"} <= family_ids
    assert response.cache.source == "family_registry"
    assert "assumptions" in response.to_dict()
    assert "bounds" in response.to_dict()
    assert "translations" in response.to_dict()
    assert "witnesses" in response.to_dict()
    assert "cache" in response.to_dict()


def test_list_providers_and_capabilities_do_not_require_tools() -> None:
    api = get_verification_api(reset=True)
    providers = api.list_providers()
    assert providers.status is VerificationStatus.DECLARATIVE
    provider_ids = {item["provider_id"] for item in providers.result["providers"]}
    assert {"z3", "cvc5"} <= provider_ids
    for item in providers.result["providers"]:
        assert item["availability"] in {
            FeatureAvailability.DECLARED.value,
            "declared",
        }

    caps = api.provider_capabilities()
    assert caps.status is VerificationStatus.DECLARATIVE
    assert caps.result["count"] >= 2
    assert "z3" in caps.result["capabilities"]

    missing = api.provider_capabilities("not-a-backend")
    assert missing.status is VerificationStatus.UNSUPPORTED
    assert "provider:not-a-backend" in missing.unsupported_features


def test_compile_check_portfolio_and_counterexample() -> None:
    api = get_verification_api(reset=True)

    compiled = api.compile_verification_artifact(
        {"obligation_id": "obl:unit", "statement": "true"},
        request_id="req:compile",
    )
    assert compiled.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.PARTIAL,
    }
    assert compiled.authority is VerificationAuthority.BOUNDED
    assert compiled.result["obligation_id"] == "obl:unit"
    assert "compilation" in compiled.result
    assert compiled.request_id == "req:compile"

    unsupported_target = api.compile_verification_artifact(
        {"obligation_id": "obl:x"},
        target="not-a-target",
    )
    assert unsupported_target.status is VerificationStatus.UNSUPPORTED
    assert "compile_target:not-a-target" in unsupported_target.unsupported_features

    checked = api.check(
        {
            "statement": "(assert true)",
            "source": "(assert true)",
            "logic_family": "first_order",
            "query_kind": "satisfiability",
            "assumption_ids": ("env:trusted",),
        },
        request_id="req:check",
    )
    assert checked.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.UNAVAILABLE,
        VerificationStatus.ERROR,
    }
    assert "status" in checked.to_dict()
    assert "authority" in checked.to_dict()
    assert "assumptions" in checked.to_dict()
    assert checked.assumptions == ("env:trusted",)
    assert "bounds" in checked.to_dict()
    assert "cache" in checked.to_dict()

    portfolio = api.run_portfolio(
        {
            "obligation_id": "obl:portfolio",
            "property_kind": "satisfiability",
            "statement": "P",
            "assumption_ids": ("a:1",),
        }
    )
    assert portfolio.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.PARTIAL,
    }
    assert portfolio.authority is VerificationAuthority.BOUNDED
    assert portfolio.assumptions == ("a:1",)
    assert portfolio.result["attempt_count"] >= 1

    explained = api.explain_counterexample(
        {"kind": "model", "model": {"x": "1"}, "summary": "x assigned 1"}
    )
    assert explained.status is VerificationStatus.SUCCEEDED
    assert explained.authority is VerificationAuthority.BOUNDED
    assert explained.result["model"] == {"x": "1"}
    assert explained.witnesses


def test_monitor_receipt_advisor_and_opt_in_ops() -> None:
    from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
        Clock,
        Event,
        Formula,
        TimeValue,
        Trace,
        TraceKind,
    )

    api = get_verification_api(reset=True)
    formula = Formula(operator="atom", proposition="p")
    trace = Trace(
        clock=Clock(clock_id="c1"),
        events=(
            Event(
                event_id="e1",
                event_type="obs",
                time=TimeValue(0),
                true_propositions=("p",),
            ),
        ),
        kind=TraceKind.FINITE,
    )
    monitored = api.monitor(formula, trace, request_id="req:mon")
    assert monitored.status is VerificationStatus.SUCCEEDED
    assert monitored.authority is VerificationAuthority.MONITOR
    assert monitored.result["verdict"] in {"true", "false", "unknown", ""}

    receipt = api.verify_receipt(
        {
            "receipt_id": "rcpt:1",
            "authority": "bounded",
            "digest": "a" * 64,
            "kind": "proof_receipt",
        }
    )
    assert receipt.status is VerificationStatus.SUCCEEDED
    assert receipt.authority is VerificationAuthority.BOUNDED

    missing_receipt = api.verify_receipt(None)
    assert missing_receipt.status is VerificationStatus.INVALID
    assert "receipt" in missing_receipt.unsupported_features

    advised = api.advise({"goal_text": "prove P -> Q"}, provider="static")
    assert advised.status is VerificationStatus.SUCCEEDED
    assert advised.authority is VerificationAuthority.ADVISORY
    assert "never" in advised.result["authority_note"].lower()

    unknown_advisor = api.advise({"goal_text": "prove P"}, provider="not-real")
    assert unknown_advisor.status is VerificationStatus.UNSUPPORTED
    assert "advisor:not-real" in unknown_advisor.unsupported_features

    disabled_attest = api.attest_receipt({"receipt_id": "r"}, backend_mode="disabled")
    assert disabled_attest.status is VerificationStatus.UNAVAILABLE
    assert "attestation_backend" in disabled_attest.unsupported_features

    no_install = api.install_provider("z3")
    assert no_install.status is VerificationStatus.UNSUPPORTED
    assert "install_without_opt_in" in no_install.unsupported_features

    install_unbound = api.install_provider("z3", allow_install=True)
    assert install_unbound.status is VerificationStatus.UNAVAILABLE
    assert "provider_installer" in install_unbound.unsupported_features

    probe = api.probe_provider("z3")
    assert probe.status in {
        VerificationStatus.SUCCEEDED,
        VerificationStatus.UNAVAILABLE,
    }
    assert "available" in probe.result

    missing_probe = api.probe_provider("missing-backend")
    assert missing_probe.status is VerificationStatus.UNSUPPORTED


def test_package_and_api_lazy_exports() -> None:
    import ipfs_datasets_py.logic as logic_pkg
    import ipfs_datasets_py.logic.api as api

    assert "verification_api" in logic_pkg.__all__
    module = logic_pkg.verification_api
    assert module.LOGIC_VERIFICATION_API_INTERFACE == LOGIC_VERIFICATION_API_INTERFACE

    # Additive surface via getattr; not part of frozen exact_exports.
    assert api.LogicVerificationAPI.__name__ == "LogicVerificationAPI"
    assert callable(api.get_verification_api)
    response = api.list_logic_families()
    assert response.status.value == VerificationStatus.DECLARATIVE.value


def test_submodule_registry_lists_verification_api() -> None:
    from ipfs_datasets_py.logic.submodule_registry import (
        logic_submodule_names,
        logic_submodule_spec,
    )

    names = logic_submodule_names()
    assert "verification_api" in names
    assert "software_verification" in names
    spec = logic_submodule_spec("verification_api")
    assert spec.module == "ipfs_datasets_py.logic.verification_api"
    assert "LogicVerificationAPI" in spec.public_symbols
    assert "public_api" in spec.roles


def test_declared_backend_catalog_matches_registry() -> None:
    from ipfs_datasets_py.logic.backends.registry import (
        declared_backend_catalog,
        default_backend_registry,
    )

    catalog = declared_backend_catalog()
    registry = default_backend_registry()
    assert {item["provider_id"] for item in catalog} == set(registry)
    for item in catalog:
        assert item["availability"] == "declared"
        assert item["source"] == "backend_registry"
        assert item["logic_families"]


def test_module_level_wrappers_match_facade() -> None:
    from ipfs_datasets_py.logic import verification_api as vap

    via_module = vap.list_providers()
    via_facade = get_verification_api().list_providers()
    assert via_module.status.value == via_facade.status.value
    assert via_module.result["count"] == via_facade.result["count"]
    assert vap.get_verification_api().to_dict()["interface"] == (
        LOGIC_VERIFICATION_API_INTERFACE
    )
