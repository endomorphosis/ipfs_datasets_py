from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_ir.model import SecurityIR
from ipfs_datasets_py.logic.security_ir.xaman.adapter import (
    XamanAdapterError,
    XamanEvidenceRequirement,
    XamanSecurityAdapter,
    adapt_xaman_security_ir,
    to_legacy_xaman_security_ir,
    validate_xaman_security_ir,
)
from ipfs_datasets_py.logic.security_ir.xaman.config import (
    XamanAdapterConfig,
    XamanConfigError,
    XamanSourceConfig,
)


FIXTURE = (
    Path(__file__).parents[4] / "fixtures/security_ir/v1/xaman_model.json"
)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _config(
    *,
    task_id: str = "PORTAL-CXTP-074",
    artifact_path: str = (
        "security_ir_artifacts/corpora/xaman-app/source-manifest.json"
    ),
) -> XamanAdapterConfig:
    corpus = _payload()["metadata"]["corpus"]
    return XamanAdapterConfig(
        config_id="config:xaman-golden",
        source=XamanSourceConfig(
            source_id="source:xaman-app",
            uri=corpus["source_url"],
            revision=corpus["pinned_commit"],
            review_status="trusted_fixture",
        ),
        task_ids={"runtime_trace": task_id},
        artifact_paths={"source_manifest": artifact_path},
    )


def test_golden_xaman_declaration_has_explicit_source_and_config_bindings() -> None:
    payload = _payload()
    result = XamanSecurityAdapter(_config()).adapt(payload)

    assert isinstance(result.declaration, SecurityIR)
    assert result.declaration.declaration_id == payload["model_id"]
    assert result.declaration.sources[0].source_id == "source:xaman-app"
    assert result.declaration.sources[0].revision == (
        payload["metadata"]["corpus"]["pinned_commit"]
    )
    assert all(
        "source:xaman-app" in record.source_ids
        for record in (
            *result.declaration.principals,
            *result.declaration.assets,
            *result.declaration.resources,
            *result.declaration.policies,
            *result.declaration.assumptions,
            *result.declaration.claims,
        )
    )
    extension = result.declaration.extensions[0]
    assert extension.vocabulary == "security.xaman"
    assert extension.required is True
    assert extension.payload["config_binding"] == {
        "config_id": "config:xaman-golden"
    }
    assert extension.payload["source_binding"] == {
        "source_id": "source:xaman-app"
    }
    assert to_legacy_xaman_security_ir(result) == payload
    assert validate_xaman_security_ir(result.declaration) is result.declaration
    assert (
        to_legacy_xaman_security_ir(result, as_model=True).to_dict()
        == payload
    )


def test_blocking_assumptions_are_evidence_requirements_not_proofs() -> None:
    result = adapt_xaman_security_ir(_payload(), config=_config())

    assert result.authority == "evidence_requirement"
    assert result.proof_authoritative is False
    assert result.blockers
    assert {item.assumption_id for item in result.blockers} == {
        "A1",
        "A2",
        "A3",
        "A6",
    }
    assert all(
        isinstance(item, XamanEvidenceRequirement)
        and item.required_evidence
        and item.claim_ids
        for item in result.evidence_requirements
    )
    declaration = result.declaration.to_dict()
    assert "proof_obligations" not in declaration
    assert "solver_results" not in declaration
    assert "runtime_traces" not in declaration
    assert "prover_targets" not in json.dumps(declaration, sort_keys=True)
    assert result.verification_data.proof_obligations
    assert result.verification_data.runtime_traces


def test_task_ids_and_artifact_paths_do_not_change_shared_model_identity() -> None:
    first = adapt_xaman_security_ir(_payload(), config=_config())
    second = adapt_xaman_security_ir(
        _payload(),
        config=_config(
            task_id="PORTAL-CXTP-999",
            artifact_path="runtime/xaman/source-manifest.json",
        ),
    )

    assert first.configuration_digest != second.configuration_digest
    assert first.declaration.to_dict() == second.declaration.to_dict()
    assert first.declaration.cid == second.declaration.cid
    serialized = json.dumps(first.declaration.to_dict(), sort_keys=True)
    assert "PORTAL-CXTP-074" not in serialized
    assert "security_ir_artifacts" not in serialized


def test_source_revision_changes_identity_but_verification_does_not() -> None:
    baseline_payload = _payload()
    verification_changed = copy.deepcopy(baseline_payload)
    verification_changed["proof_obligations"][0]["status"] = "UNKNOWN"
    verification_changed["runtime_traces"][0]["conformance_status"] = (
        "violated"
    )
    source_changed = copy.deepcopy(baseline_payload)
    source_changed["metadata"]["corpus"]["pinned_commit"] = "new-revision"
    source_config = XamanAdapterConfig(
        source=XamanSourceConfig(
            source_id="source:xaman-app",
            uri=source_changed["metadata"]["corpus"]["source_url"],
            revision="new-revision",
        )
    )

    baseline = adapt_xaman_security_ir(baseline_payload, _config())
    run_changed = adapt_xaman_security_ir(verification_changed, _config())
    revision_changed = adapt_xaman_security_ir(
        source_changed, source_config
    )

    assert baseline.declaration.cid == run_changed.declaration.cid
    assert baseline.verification_data.to_dict() != (
        run_changed.verification_data.to_dict()
    )
    assert baseline.declaration.cid != revision_changed.declaration.cid


def test_source_binding_is_pinned_and_fails_closed_on_mismatch() -> None:
    payload = _payload()
    mismatched = XamanAdapterConfig(
        source=XamanSourceConfig(
            source_id="source:xaman-app",
            uri=payload["metadata"]["corpus"]["source_url"],
            revision="different-revision",
        )
    )

    with pytest.raises(XamanAdapterError, match="source revision"):
        adapt_xaman_security_ir(payload, config=mismatched)

    without_metadata = copy.deepcopy(payload)
    del without_metadata["metadata"]["corpus"]["pinned_commit"]
    with pytest.raises(XamanAdapterError, match="pinned_commit"):
        adapt_xaman_security_ir(without_metadata, config=_config())


def test_missing_evidence_requirement_fails_closed() -> None:
    config = XamanAdapterConfig(
        source=_config().source,
        evidence_requirements={"A1": ("cryptographic review",)},
    )

    with pytest.raises(XamanAdapterError, match="A2, A3, A6, A9"):
        adapt_xaman_security_ir(_payload(), config=config)


def test_adapter_defensively_copies_input_and_configuration_is_immutable() -> None:
    payload = _payload()
    config = _config()
    result = adapt_xaman_security_ir(payload, config=config)
    declaration = result.declaration.to_dict()

    payload["claims"][0]["description"] = "mutated"
    payload["metadata"]["corpus"]["pinned_commit"] = "mutated"
    payload["runtime_traces"][0]["conformance_status"] = "violated"

    assert result.declaration.to_dict() == declaration
    assert to_legacy_xaman_security_ir(result)["claims"][0]["description"] != (
        "mutated"
    )
    with pytest.raises(TypeError):
        config.task_ids["runtime_trace"] = "PORTAL-CXTP-999"
    with pytest.raises(FrozenInstanceError):
        config.config_id = "config:changed"
    assert XamanAdapterConfig.from_dict(config.to_dict()) == config


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/source-manifest.json",
        "../source-manifest.json",
        "corpus/../source-manifest.json",
    ],
)
def test_artifact_paths_must_be_safe_repository_relative_paths(path: str) -> None:
    with pytest.raises(XamanConfigError, match="repository-relative"):
        _config(artifact_path=path)


def test_non_xaman_and_unknown_extensions_fail_closed() -> None:
    payload = _payload()
    for claim in payload["claims"]:
        claim["domain"] = "withdrawals"
    with pytest.raises(XamanAdapterError, match="outside Xaman"):
        adapt_xaman_security_ir(payload, config=_config())

    payload = _payload()
    payload["runtime_hint"] = {"mode": "mutable"}
    with pytest.raises(XamanAdapterError, match="unknown Xaman legacy field"):
        adapt_xaman_security_ir(payload, config=_config())
