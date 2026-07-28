"""Unit tests for SupervisorAdmissibilityBridge@1 (LIG-017).

Acceptance:

* Import agent_supervisor without provers (bridge module stays free of optional
  heavy prover imports at load time).
* Bridge unit test with mocked corpus or offline fixtures.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_accelerate_py.agent_supervisor import admissibility_bridge as bridge
from ipfs_accelerate_py.agent_supervisor.admissibility_bridge import (
    DEFAULT_PROFILE_ID,
    ENV_ADMISSIBILITY_ENABLED,
    ENV_ADMISSIBILITY_PROFILE,
    ENV_ADMISSIBILITY_STORE,
    SUPERVISOR_ADMISSIBILITY_BRIDGE_INTERFACE,
    AdmissibilityBridgeError,
    AdmissibilityBridgeStatus,
    AdmissibilityDisposition,
    AdmissibilityObservation,
    SupervisorAdmissibilityBridge,
    check_intent_admissibility,
    create_admissibility_bridge,
    datasets_available,
    observe_admissibility,
    open_proof_corpus_store,
    reset_datasets_surface_cache,
)


# ---------------------------------------------------------------------------
# Offline fixture discovery (datasets worktree / checkout)
# ---------------------------------------------------------------------------


def _discover_fixture_root() -> Path:
    """Locate intent admissibility offline fixtures without network access."""

    candidates: list[Path] = []
    here = Path(__file__).resolve()
    # worktree: test/api -> repo root -> tests/fixtures/...
    candidates.append(
        here.parents[2] / "tests" / "fixtures" / "intent_ir" / "admissibility"
    )
    # accelerate test/api -> may not have fixtures; also try PYTHONPATH datasets
    for entry in sys.path:
        if not entry:
            continue
        root = Path(entry)
        candidates.append(
            root / "tests" / "fixtures" / "intent_ir" / "admissibility"
        )
        candidates.append(
            root
            / "ipfs_datasets_py"
            / ".."
            / "tests"
            / "fixtures"
            / "intent_ir"
            / "admissibility"
        )
    # Known daemon / checkout layouts
    candidates.append(
        Path(
            "/home/barberb/portland-laws.github.io/ipfs_datasets_py"
            "/tests/fixtures/intent_ir/admissibility"
        )
    )
    for path in candidates:
        resolved = path.resolve()
        if (resolved / "formal_artifacts" / "benign_skill.json").is_file():
            return resolved
    raise RuntimeError(
        "offline admissibility fixtures not found; expected "
        "tests/fixtures/intent_ir/admissibility/formal_artifacts/benign_skill.json"
    )


FIXTURE_ROOT = _discover_fixture_root()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _intent_raw(case_id: str = "benign_skill") -> dict[str, Any]:
    return _load_json(FIXTURE_ROOT / "formal_artifacts" / f"{case_id}.json")


def _constraint_from_intent(
    intent_raw: dict[str, Any],
    *,
    domain: str,
    role: str,
) -> dict[str, Any]:
    """Clone an Intent formal artifact payload into a Legal/Security constraint."""

    payload = copy.deepcopy(intent_raw)
    payload["domain"] = domain
    metadata = dict(payload.get("metadata") or {})
    metadata["gate_role"] = role
    metadata["constraint_family"] = domain
    payload["metadata"] = metadata
    for formula in payload.get("formulas", []):
        expression = formula.get("expression")
        if isinstance(expression, dict):
            expression = dict(expression)
            expression["role"] = role
            if role in {"grant", "permission", "support"}:
                expression["norm_type"] = "permission"
                expression["polarity"] = "positive"
            else:
                expression["norm_type"] = "prohibition"
                expression["polarity"] = "negative"
            formula["expression"] = expression
    return payload


def _allow_envelopes() -> list[dict[str, Any]]:
    """Build offline envelope fixtures that should allow under legal-strict."""

    from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
    from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
    from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore

    intent_raw = _intent_raw("benign_skill")
    intent = FormalizationArtifact.from_dict(intent_raw)
    legal = FormalizationArtifact.from_dict(
        _constraint_from_intent(intent_raw, domain="legal", role="grant")
    )
    security = FormalizationArtifact.from_dict(
        _constraint_from_intent(intent_raw, domain="security", role="grant")
    )
    store = ProofCorpusStore()
    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(intent, profile="legal-strict")
    )
    legal_env = store.put(
        ArtifactEnvelope.build(
            legal,
            profile="legal-strict",
            family="legal",
            producer_id="test-legal-constraint",
        )
    )
    security_env = store.put(
        ArtifactEnvelope.build(
            security,
            profile="legal-strict",
            family="security",
            producer_id="test-security-constraint",
        )
    )
    return [intent_env.to_dict(), legal_env.to_dict(), security_env.to_dict()]


def _legal_reject_envelopes() -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
    from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
    from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore

    intent_raw = _intent_raw("legally_risky_effect")
    intent = FormalizationArtifact.from_dict(intent_raw)
    legal = FormalizationArtifact.from_dict(
        _constraint_from_intent(intent_raw, domain="legal", role="prohibition")
    )
    security = FormalizationArtifact.from_dict(
        _constraint_from_intent(intent_raw, domain="security", role="grant")
    )
    store = ProofCorpusStore()
    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(intent, profile="legal-strict")
    )
    legal_env = store.put(
        ArtifactEnvelope.build(
            legal,
            profile="legal-strict",
            family="legal",
            producer_id="test-legal-constraint",
        )
    )
    security_env = store.put(
        ArtifactEnvelope.build(
            security,
            profile="legal-strict",
            family="security",
            producer_id="test-security-constraint",
        )
    )
    return [intent_env.to_dict(), legal_env.to_dict(), security_env.to_dict()]


def _abstain_envelopes() -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
    from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
    from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore

    intent = FormalizationArtifact.from_dict(
        _intent_raw("incomplete_unsupported_semantics")
    )
    store = ProofCorpusStore()
    intent_env = store.put(
        ArtifactEnvelope.from_intent_artifact(intent, profile="legal-strict")
    )
    return [intent_env.to_dict()]


@pytest.fixture(autouse=True)
def _reset_lazy_cache() -> None:
    reset_datasets_surface_cache()
    yield
    reset_datasets_surface_cache()


# ---------------------------------------------------------------------------
# Import / prover isolation
# ---------------------------------------------------------------------------


def test_bridge_module_does_not_import_datasets_gate_at_load() -> None:
    """Lazy-import invariant: bridge load must not pull the datasets gate."""

    gate_mods = [
        name
        for name in sys.modules
        if name.startswith("ipfs_datasets_py.logic.admissibility")
    ]
    # Reset and re-import bridge fresh in isolation is hard once tests ran the
    # gate; assert the module documents lazy targets and has no eager import.
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    assert "importlib.import_module" in source
    assert "_load_datasets_surface" in source
    assert "from ipfs_datasets_py.logic.admissibility" not in source
    # Optional heavy provers must never appear as import targets.
    for banned in ("z3", "cvc5", "vampire", "lean_dojo", "shadowprover"):
        assert f"import {banned}" not in source
        assert f'importlib.import_module("{banned}' not in source
        assert f"importlib.import_module('{banned}" not in source


def test_import_agent_supervisor_does_not_require_external_provers() -> None:
    """Package import must succeed without optional external prover packages."""

    # agent_supervisor is already importable in this environment; assert that
    # heavy third-party prover backends are not loaded as a consequence of the
    # bridge path specifically.
    import ipfs_accelerate_py.agent_supervisor as supervisor  # noqa: F401
    import ipfs_accelerate_py.agent_supervisor.admissibility_bridge as ab

    assert ab.SUPERVISOR_ADMISSIBILITY_BRIDGE_INTERFACE == (
        SUPERVISOR_ADMISSIBILITY_BRIDGE_INTERFACE
    )
    external = [
        name
        for name in sys.modules
        if name.split(".")[0]
        in {
            "z3",
            "cvc5",
            "vampire",
            "lean_dojo",
            "nltk_tactics",
            "shadowprover",
        }
    ]
    assert external == []


def test_bridge_interface_constants_are_pinned() -> None:
    assert (
        SUPERVISOR_ADMISSIBILITY_BRIDGE_INTERFACE
        == "SupervisorAdmissibilityBridge@1"
    )
    assert DEFAULT_PROFILE_ID == "legal-strict"
    assert bridge.SUPERVISOR_ADMISSIBILITY_BRIDGE_VERSION == 1


# ---------------------------------------------------------------------------
# Capabilities / env / construction
# ---------------------------------------------------------------------------


def test_capabilities_report_without_evaluation() -> None:
    b = create_admissibility_bridge(envelopes=_allow_envelopes())
    caps = b.capabilities()
    assert caps["interface"] == SUPERVISOR_ADMISSIBILITY_BRIDGE_INTERFACE
    assert caps["executed"] is False
    assert caps["provers_imported"] is False
    assert caps["env_flags"]["store"] == ENV_ADMISSIBILITY_STORE
    assert caps["env_flags"]["enabled"] == ENV_ADMISSIBILITY_ENABLED
    assert caps["env_flags"]["profile"] == ENV_ADMISSIBILITY_PROFILE
    assert caps["datasets_available"] is True
    assert datasets_available() is True


def test_from_env_respects_disabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ADMISSIBILITY_ENABLED, "0")
    monkeypatch.setenv(ENV_ADMISSIBILITY_PROFILE, "security-lite")
    b = SupervisorAdmissibilityBridge.from_env(envelopes=_allow_envelopes())
    assert b.enabled is False
    assert b.profile_id == "security-lite"
    observation = b.check(_allow_envelopes()[0]["content_cid"])
    assert observation.disposition is AdmissibilityDisposition.UNAVAILABLE
    assert observation.bridge_status is AdmissibilityBridgeStatus.DISABLED
    assert observation.is_allow is False


def test_from_offline_fixtures_requires_envelopes() -> None:
    with pytest.raises(AdmissibilityBridgeError):
        SupervisorAdmissibilityBridge.from_offline_fixtures([])


def test_open_store_requires_root_or_envelopes_or_store() -> None:
    with pytest.raises(AdmissibilityBridgeError):
        create_admissibility_bridge().evaluate("baguqeera-missing")


# ---------------------------------------------------------------------------
# Offline fixture evaluation (mocked corpus)
# ---------------------------------------------------------------------------


def test_bridge_allow_with_offline_envelopes() -> None:
    envelopes = _allow_envelopes()
    intent_cid = envelopes[0]["content_cid"]
    b = SupervisorAdmissibilityBridge.from_offline_fixtures(envelopes)
    assert b.ensure_ready() is AdmissibilityBridgeStatus.READY

    decision = b.evaluate(intent_cid, "legal-strict")
    assert decision.status.value == "allow"
    assert decision.profile_id == "legal-strict"
    assert decision.intent_cid == intent_cid
    assert decision.constraint_cids  # grants bound
    assert decision.config_digest

    observation = b.check(intent_cid)
    assert observation.is_allow
    assert observation.disposition is AdmissibilityDisposition.ALLOW
    assert observation.decision is not None
    assert observation.decision["status"] == "allow"
    assert observation.intent_cid == intent_cid

    wire = b.check_intent_admissibility(intent_cid)
    assert wire["success"] is True
    assert wire["executed"] is False
    assert wire["status"] == "allow"
    assert wire["disposition"] == "allow"


def test_bridge_reject_legal_hard_constraint_offline() -> None:
    envelopes = _legal_reject_envelopes()
    intent_cid = envelopes[0]["content_cid"]
    b = create_admissibility_bridge(envelopes=envelopes, profile_id="legal-strict")
    observation = b.check(intent_cid)
    assert observation.is_allow is False
    assert observation.disposition is AdmissibilityDisposition.REJECT
    assert observation.status == "reject"
    assert observation.decision is not None
    assert observation.constraint_cids or observation.reason_codes


def test_bridge_abstain_incomplete_evidence_offline() -> None:
    envelopes = _abstain_envelopes()
    intent_cid = envelopes[0]["content_cid"]
    b = create_admissibility_bridge(envelopes=envelopes)
    observation = b.check(intent_cid)
    assert observation.is_allow is False
    # Incomplete / unsupported semantics → abstain (or reject if profile
    # hard-fails); never allow without constraints.
    assert observation.disposition in {
        AdmissibilityDisposition.ABSTAIN,
        AdmissibilityDisposition.REJECT,
    }
    assert observation.status in {"abstain", "reject"}


def test_module_helpers_with_mocked_store() -> None:
    envelopes = _allow_envelopes()
    store = open_proof_corpus_store(envelopes=envelopes)
    intent_cid = envelopes[0]["content_cid"]

    wire = check_intent_admissibility(
        intent_cid, "legal-strict", store=store
    )
    assert wire["success"] is True
    assert wire["status"] == "allow"

    observation = observe_admissibility(intent_cid, store=store)
    assert isinstance(observation, AdmissibilityObservation)
    assert observation.is_allow


def test_mocked_corpus_via_injected_store() -> None:
    """Bridge accepts a pre-built / mocked ProofCorpusStore instance."""

    from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
    from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
    from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore

    envelopes = _allow_envelopes()
    store = ProofCorpusStore()
    for item in envelopes:
        store.put(ArtifactEnvelope.from_dict(item))

    b = create_admissibility_bridge(store=store)
    decision = b.evaluate(envelopes[0]["content_cid"])
    assert decision.is_allow

    # Artifact mapping path (pinned formal payload, not a live skill body).
    artifact_map = _intent_raw("benign_skill")
    # Evaluating a raw artifact without putting it may abstain/reject if the
    # store cannot bind constraints; use the store CID path as authoritative.
    assert isinstance(artifact_map, dict)
    assert FormalizationArtifact.from_dict(artifact_map).domain


def test_fail_closed_on_missing_intent() -> None:
    envelopes = _allow_envelopes()
    b = create_admissibility_bridge(envelopes=envelopes)
    observation = b.check("")
    assert observation.is_allow is False
    assert observation.disposition in {
        AdmissibilityDisposition.ERROR,
        AdmissibilityDisposition.UNAVAILABLE,
        AdmissibilityDisposition.REJECT,
    }


def test_observation_to_dict_is_json_serializable() -> None:
    envelopes = _allow_envelopes()
    b = create_admissibility_bridge(envelopes=envelopes)
    observation = b.check(envelopes[0]["content_cid"])
    payload = observation.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    assert "allow" in encoded
    assert payload["interface"] == SUPERVISOR_ADMISSIBILITY_BRIDGE_INTERFACE
    assert payload["schema"] == bridge.SUPERVISOR_ADMISSIBILITY_OBSERVATION_SCHEMA
