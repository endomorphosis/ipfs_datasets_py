"""Integration tests for source and domain adapters into shared software-verification IR."""

from __future__ import annotations

import pytest

from ipfs_accelerate_py.agent_supervisor.code_security_facts import (
    SOFTWARE_VERIFICATION_SECURITY_FACT_COMPAT,
    security_observation_for_software_verification,
    security_observation_payload,
)
from ipfs_accelerate_py.agent_supervisor.program_ast_adapters import (
    SOFTWARE_VERIFICATION_PROGRAM_AST_COMPAT,
    program_evidence_for_software_verification,
)
from ipfs_datasets_py.logic.software_verification.domain_adapters import (
    INTENT_SOFTWARE_VERIFICATION_ADAPTER,
    SECURITY_SOFTWARE_VERIFICATION_ADAPTER,
    DomainAdapterError,
    IntentSoftwareVerificationAdapter,
    SecuritySoftwareVerificationAdapter,
    adapt_intent_view,
    adapt_security_view,
)
from ipfs_datasets_py.logic.software_verification.ir import SoftwareVerificationIR
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    SOURCE_SOFTWARE_VERIFICATION_ADAPTER,
    SourceAdapterStatus,
    SourceSoftwareVerificationAdapter,
    adapt_source_to_software_verification,
)


PYTHON_SRC = """
def abs_val(x):
    if x < 0:
        return -x
    return x
"""

JS_SRC = """
function add(x, y) {
  return x + y;
}
"""

TS_SRC = """
export function clamp(n: number, lo: number, hi: number) {
  if (n < lo) {
    return lo;
  }
  if (n > hi) {
    return hi;
  }
  return n;
}
"""

UNSUPPORTED_PYTHON = """
class Counter:
    def __init__(self):
        self.n = 0

async def tick():
    await asyncio.sleep(0)
"""


def test_interfaces_are_versioned() -> None:
    assert SOURCE_SOFTWARE_VERIFICATION_ADAPTER.endswith("@1")
    assert INTENT_SOFTWARE_VERIFICATION_ADAPTER.endswith("@1")
    assert SECURITY_SOFTWARE_VERIFICATION_ADAPTER.endswith("@1")
    assert SOFTWARE_VERIFICATION_PROGRAM_AST_COMPAT
    assert SOFTWARE_VERIFICATION_SECURITY_FACT_COMPAT


def test_python_source_lowers_to_program_and_shared_ir() -> None:
    result = adapt_source_to_software_verification(PYTHON_SRC, path="abs_val.py")
    assert result.status in {
        SourceAdapterStatus.SUCCESS,
        SourceAdapterStatus.PARTIAL,
    }
    assert result.program is not None
    assert isinstance(result.program, ProgramIR)
    assert result.document is not None
    assert isinstance(result.document, SoftwareVerificationIR)
    assert result.document.sources
    assert result.document.declarations
    assert result.document.assumptions
    assumption_kinds = {item.kind.value for item in result.document.assumptions}
    assert "platform" in assumption_kinds or "semantic" in assumption_kinds
    statements = " ".join(item.statement.lower() for item in result.document.assumptions)
    assert "runtime" in statements or "sequential" in statements
    assert "memory" in statements
    assert "undefined" in statements
    assert result.backend_requests
    assert all(item.attributes.get("fake_success_forbidden") for item in result.backend_requests)
    assert result.fake_backend_success is False
    assert result.evidence is not None
    assert result.evidence.status in {"success", "partial"}


def test_javascript_and_typescript_source_lowers() -> None:
    js = adapt_source_to_software_verification(JS_SRC, path="add.js")
    assert js.supported
    assert js.program is not None
    assert js.document is not None
    assert js.language == "javascript"
    assert js.backend_requests
    assert "javascript.opaque_function_body" in js.unsupported_constructs

    ts = adapt_source_to_software_verification(TS_SRC, path="clamp.ts")
    assert ts.supported
    assert ts.program is not None
    assert ts.document is not None
    assert ts.language == "typescript"
    assert ts.backend_requests
    assert ts.fake_backend_success is False


def test_unsupported_python_constructs_are_retained() -> None:
    result = adapt_source_to_software_verification(
        UNSUPPORTED_PYTHON, path="unsupported.py"
    )
    assert result.status in {
        SourceAdapterStatus.PARTIAL,
        SourceAdapterStatus.UNSUPPORTED,
    }
    assert result.unsupported_constructs
    assert any("class" in item or "async" in item for item in result.unsupported_constructs)
    if result.document is not None:
        assert result.document.diagnostics or result.unsupported_constructs


def test_source_adapter_class_interface() -> None:
    adapter = SourceSoftwareVerificationAdapter()
    result = adapter.adapt("def id(x):\n    return x\n", path="id.py")
    assert result.interface == SOURCE_SOFTWARE_VERIFICATION_ADAPTER
    assert result.program is not None
    assert result.document is not None


def test_intent_dynamic_hoare_and_vc_preserve_domain_identity() -> None:
    identity = "intent:demo.workflow.transfer"
    fixture = {
        "domain_identity": identity,
        "kind": "dynamic_hoare",
        "statement": "Transfer preserves non-negative balances.",
        "hoare": {
            "pre": "balance >= amount",
            "program": "transfer(amount)",
            "post": "balance' == balance - amount",
        },
        "obligations": [
            {
                "obligation_id": "intent:demo.workflow.transfer.vc0",
                "statement": "pre implies wp(program, post)",
                "kind": "vc",
            }
        ],
        "source": {
            "path": "fixtures/intent/transfer.json",
            "text": '{"workflow":"transfer"}',
            "language": "json",
        },
    }
    result = adapt_intent_view(fixture)
    assert result.domain.value == "intent"
    assert result.domain_identity == identity
    assert result.identity_stable is True
    assert result.document is not None
    assert result.document.metadata.to_dict()["domain_identity"] == identity
    assert result.document.extensions.to_dict()["lfv.domain.identity"] == identity
    assert result.backend_requests
    assert result.fake_backend_success is False
    assert any(item.kind.value in {"contract", "axiom"} or item.kind == "contract"
               for item in result.document.declarations)

    vc = adapt_intent_view(
        {
            "domain_identity": "intent:demo.safety.lock",
            "kind": "vc",
            "statement": "Lock acquisition VC is valid.",
            "max_vc_steps": 16,
            "verification_conditions": [{"goal": "locked"}],
        }
    )
    assert vc.identity_stable is True
    assert vc.document is not None
    assert vc.document.bounds
    assert vc.document.properties[0].kind.value == "validity"


def test_intent_adapter_rejects_missing_identity() -> None:
    with pytest.raises(DomainAdapterError):
        adapt_intent_view({"kind": "safety", "statement": "no identity"})


def test_security_transition_system_and_vc() -> None:
    identity = "security:demo.authz.session"
    fixture = {
        "domain_identity": identity,
        "kind": "transition_system",
        "statement": "Unauthorized sessions cannot reach admin.",
        "states": [
            {"state_id": "logged_out", "label": "LoggedOut"},
            {"state_id": "user", "label": "User"},
            {"state_id": "admin", "label": "Admin"},
        ],
        "transitions": [
            {
                "transition_id": "login",
                "source": "logged_out",
                "target": "user",
                "guard": {"credential_ok": True},
            },
            {
                "transition_id": "escalate",
                "source": "user",
                "target": "admin",
                "guard": {"role": "admin"},
            },
        ],
        "unsupported": ["security.timing_side_channel"],
        "source": {
            "path": "fixtures/security/session.json",
            "text": '{"model":"session"}',
        },
    }
    result = adapt_security_view(fixture)
    assert result.domain.value == "security"
    assert result.domain_identity == identity
    assert result.identity_stable is True
    assert result.document is not None
    assert result.document.metadata.to_dict()["domain_identity"] == identity
    decls = {item.name: item for item in result.document.declarations}
    assert "login" in decls or any("login" in item.name for item in result.document.declarations)
    assert "security.timing_side_channel" in result.unsupported_constructs
    assert result.backend_requests
    assert result.backend_requests[0].goal_kind == "reachability"
    assert result.fake_backend_success is False

    vc = adapt_security_view(
        {
            "domain_identity": "security:demo.authz.vc",
            "kind": "vc",
            "statement": "No privilege escalation VC.",
            "vc": {"goal": "not admin_from_user"},
            "states": [],
            "transitions": [],
        }
    )
    assert vc.identity_stable is True
    assert vc.document is not None
    assert vc.backend_requests[0].goal_kind == "verification_condition"


def test_security_view_can_attach_non_authoritative_code_facts() -> None:
    before = "def f(x):\n    return x\n"
    after = "def f(x):\n    return open(x).read()\n"
    changed = {
        "path": "mod.py",
        "before_source": before,
        "after_source": after,
        "tree_id": "tree:demo",
        "diff_id": "diff:demo",
    }
    # Compatibility helper must stay non-authoritative.
    facts = security_observation_for_software_verification(changed)
    assert facts.authorizes_completion is False
    assert facts.grants_authority is False
    payload = security_observation_payload(facts)
    assert payload["authoritative"] is False
    assert payload["compat"] == SOFTWARE_VERIFICATION_SECURITY_FACT_COMPAT

    result = adapt_security_view(
        {
            "domain_identity": "security:demo.open-read",
            "kind": "transition_system",
            "states": [{"state_id": "s0"}],
            "transitions": [
                {"transition_id": "t0", "source": "s0", "target": "s0"}
            ],
        },
        changed_diff=changed,
    )
    assert result.document is not None
    observations = result.document.observations.to_dict()
    assert observations.get("code_security_authoritative") is False
    if "code_security_fact_set" in observations:
        assert observations["code_security_fact_set"]["status"] is not None


def test_program_ast_compat_helper_aligns_with_source_adapter() -> None:
    evidence = program_evidence_for_software_verification(
        PYTHON_SRC, path="abs_val.py", language="python"
    )
    result = SourceSoftwareVerificationAdapter().adapt(PYTHON_SRC, path="abs_val.py")
    assert evidence.status in {"success", "partial"}
    assert result.evidence is not None
    assert result.evidence.source_sha256 == evidence.source_sha256
    assert result.evidence.language == evidence.language


def test_domain_adapter_classes() -> None:
    intent = IntentSoftwareVerificationAdapter().adapt(
        {
            "domain_identity": "intent:class.api",
            "kind": "workflow",
            "workflow": {"steps": ["a", "b"]},
        }
    )
    assert intent.interface == INTENT_SOFTWARE_VERIFICATION_ADAPTER
    assert intent.identity_stable is True

    security = SecuritySoftwareVerificationAdapter().adapt(
        {
            "domain_identity": "security:class.api",
            "kind": "transition_system",
            "states": [{"id": "s"}],
            "transitions": [],
        }
    )
    assert security.interface == SECURITY_SOFTWARE_VERIFICATION_ADAPTER
    assert security.identity_stable is True


def test_malformed_python_is_reported() -> None:
    result = adapt_source_to_software_verification("def broken(:\n", path="broken.py")
    assert result.status is SourceAdapterStatus.MALFORMED
    assert result.diagnostics
    assert result.program is None
