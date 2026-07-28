"""Unit contracts for InvocationIntentEnvelope@1."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.intent_ir.invocation import (
    ARGUMENT_COMMITMENT_DOMAIN,
    INVOCATION_ENVELOPE_IDENTITY_DOMAIN,
    INVOCATION_ENVELOPE_INTERFACE,
    INVOCATION_ENVELOPE_SCHEMA_VERSION,
    MAX_JSON_DEPTH,
    ActorBinding,
    ArgumentCommitment,
    AudienceBinding,
    DelegationLink,
    DiagnosticSeverity,
    EnvironmentBinding,
    InvocationAssumption,
    InvocationDiagnostic,
    InvocationEnvelopeValidationError,
    InvocationIntentEnvelope,
    InvocationKind,
    InvocationScope,
    PolicyRequirements,
    PurposeContext,
    RollbackStep,
    ScopeEntry,
    ScopeKind,
    SourceBinding,
    SourceMapEntry,
    ToolBinding,
    UnsupportedField,
    VerificationStep,
    commit_redacted_arguments,
    validate_invocation_envelope,
)


def _args(redacted: dict | None = None, **kwargs) -> ArgumentCommitment:
    payload = redacted if redacted is not None else {"query": "list fixtures"}
    return ArgumentCommitment.from_redacted(payload, **kwargs)


def _minimal_envelope(**overrides) -> InvocationIntentEnvelope:
    base = dict(
        envelope_id="inv:fixture-1",
        invocation_kind=InvocationKind.MCP_TOOL,
        source=SourceBinding(
            kind=InvocationKind.MCP_TOOL,
            source_ref="source:mcp-tool-list",
            source_id="mcp.tool.list_fixtures",
            source_revision="schema-v3",
            content_sha256="a" * 64,
            intent_document_id="intent:mcp-list",
        ),
        tenant_id="tenant:demo",
        actor=ActorBinding(
            actor_id="actor:user-1",
            kind="user",
            trust_domain="trust:corp",
            subject_attributes={"role": "analyst"},
        ),
        audience=AudienceBinding(
            audience_id="audience:dispatcher-1",
            kind="dispatcher",
            deployment_id="deploy:prod-us",
        ),
        tool=ToolBinding(
            tool_id="tool:list_fixtures",
            tool_name="list_fixtures",
            tool_version="3.1.0",
            server_id="server:fixtures",
            input_schema_id="schema:list_fixtures.input",
            input_schema_sha256="b" * 64,
        ),
        arguments=_args(),
        scope=InvocationScope(
            actions=(
                ScopeEntry(
                    entry_id="scope:action:list",
                    kind=ScopeKind.ACTION,
                    value="list_fixtures",
                ),
            ),
            effects=(
                ScopeEntry(
                    entry_id="scope:effect:read",
                    kind=ScopeKind.EFFECT,
                    value="read_metadata",
                ),
            ),
            capabilities=(
                ScopeEntry(
                    entry_id="scope:cap:fixtures.read",
                    kind=ScopeKind.CAPABILITY,
                    value="fixtures.read",
                ),
            ),
            resources=(
                ScopeEntry(
                    entry_id="scope:res:fixture-store",
                    kind=ScopeKind.RESOURCE,
                    value="resource:fixture-store",
                ),
            ),
            data_classes=(
                ScopeEntry(
                    entry_id="scope:data:public",
                    kind=ScopeKind.DATA,
                    value="public",
                ),
            ),
            network=(
                ScopeEntry(
                    entry_id="scope:net:internal",
                    kind=ScopeKind.NETWORK,
                    value="https://fixtures.internal/",
                ),
            ),
            filesystem=(
                ScopeEntry(
                    entry_id="scope:fs:none",
                    kind=ScopeKind.FILESYSTEM,
                    value="none",
                ),
            ),
            subprocess=(
                ScopeEntry(
                    entry_id="scope:sub:none",
                    kind=ScopeKind.SUBPROCESS,
                    value="none",
                ),
            ),
        ),
        purpose=PurposeContext(
            purpose="authorization-evaluation",
            jurisdiction="US-OR",
            effective_time="2026-07-28T12:00:00Z",
        ),
        environment=EnvironmentBinding(
            environment_id="env:sandbox-1",
            snapshot_digest="sha256:" + "c" * 64,
            sandbox_class="network-restricted",
            observer_id="observer:runtime-attest",
            facts={"cpu_arch": "x86_64"},
        ),
        preconditions=("caller authenticated",),
        postconditions=("response is redacted",),
        failure_modes=("tool timeout",),
        rollback=(
            RollbackStep(
                step_id="rollback:noop",
                description="No side effects to reverse",
            ),
        ),
        verification=(
            VerificationStep(
                step_id="verify:schema",
                description="Response matches output schema",
                predicate="schema_valid",
            ),
        ),
        policy=PolicyRequirements(
            policy_profile="profile:admissibility-default",
            policy_root="cid:policy-root-1",
            corpus_roots=("cid:legal-corpus-1", "cid:security-corpus-1"),
            coverage_profile="coverage:strict",
        ),
        nonce="nonce:01JABCDEFGHJKMNPQRSTVWXYZ0",
        created_at="2026-07-28T12:00:00Z",
        deadline="2026-07-28T12:05:00Z",
        trace_id="trace:request-1",
        source_maps=(
            SourceMapEntry(
                map_id="map:tool-name",
                field_path="/tool/tool_name",
                source_ref="source:mcp-tool-list",
                start_char=0,
                end_char=12,
            ),
        ),
        assumptions=(
            InvocationAssumption(
                assumption_id="assume:schema-stable",
                statement="Tool input schema is stable for this revision",
                source_ref="source:mcp-tool-list",
            ),
        ),
        diagnostics=(
            InvocationDiagnostic(
                code="invocation.info.adapted",
                message="Adapted from MCP tool record",
                severity=DiagnosticSeverity.INFO,
            ),
        ),
        unsupported_fields=(
            UnsupportedField(
                field_path="/annotations/priority",
                reason="annotation is untrusted claim, not elevated",
                source_ref="source:mcp-tool-list",
                raw_kind="annotation",
            ),
        ),
        delegation=(
            DelegationLink(
                link_id="del:user-to-agent",
                from_actor_id="actor:user-1",
                to_actor_id="actor:agent-1",
                capability_ids=("fixtures.read",),
            ),
        ),
        trust_domain="trust:corp",
    )
    base.update(overrides)
    return InvocationIntentEnvelope(**base)


def test_interface_and_schema_constants() -> None:
    assert INVOCATION_ENVELOPE_INTERFACE == "InvocationIntentEnvelope@1"
    assert INVOCATION_ENVELOPE_SCHEMA_VERSION == "invocation-intent-envelope/v1"
    assert INVOCATION_ENVELOPE_IDENTITY_DOMAIN == "invocation-intent"
    assert ARGUMENT_COMMITMENT_DOMAIN.endswith("/v1")


def test_round_trip_and_canonical_identity_stable() -> None:
    envelope = _minimal_envelope()
    assert envelope.content_digest.startswith("sha256:")
    assert envelope.content_cid.startswith("b")
    assert envelope.digest == envelope.content_digest
    assert envelope.cid == envelope.content_cid

    rebuilt = InvocationIntentEnvelope.from_dict(envelope.to_dict())
    assert rebuilt.to_dict() == envelope.to_dict()
    assert rebuilt.content_digest == envelope.content_digest
    assert rebuilt.content_cid == envelope.content_cid
    assert rebuilt.canonical_bytes() == envelope.canonical_bytes()

    validated = validate_invocation_envelope(envelope)
    assert validated.content_digest == envelope.content_digest


def test_mutation_rejected() -> None:
    envelope = _minimal_envelope()
    with pytest.raises(FrozenInstanceError):
        envelope.tenant_id = "tenant:other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        envelope.arguments.redacted_arguments["query"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        envelope.scope.actions[0].attributes["x"] = 1  # type: ignore[index]


def test_unknown_schema_version_rejected() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="unsupported"):
        _minimal_envelope(schema_version="invocation-intent-envelope/v0")


def test_unknown_top_level_field_rejected() -> None:
    payload = _minimal_envelope().to_dict()
    payload["unexpected_extension"] = True
    with pytest.raises(InvocationEnvelopeValidationError, match="unknown"):
        InvocationIntentEnvelope.from_dict(payload)


def test_semantic_mutation_changes_identity() -> None:
    first = _minimal_envelope()
    second = _minimal_envelope(
        arguments=_args({"query": "list fixtures", "limit": 10}),
    )
    assert first.content_digest != second.content_digest
    assert first.content_cid != second.content_cid

    third = _minimal_envelope(tenant_id="tenant:other")
    assert first.content_digest != third.content_digest


def test_identity_drift_rejected() -> None:
    envelope = _minimal_envelope()
    payload = envelope.to_dict()
    payload["content_digest"] = "sha256:" + "0" * 64
    with pytest.raises(InvocationEnvelopeValidationError, match="identity drift"):
        InvocationIntentEnvelope.from_dict(payload)

    payload = envelope.to_dict()
    payload["content_cid"] = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    with pytest.raises(InvocationEnvelopeValidationError, match="identity drift"):
        InvocationIntentEnvelope.from_dict(payload)


def test_argument_commitment_matches_redacted_view() -> None:
    redacted = {"path": "/tmp/report", "api_key": "[REDACTED]"}
    commitment = commit_redacted_arguments(redacted)
    bound = ArgumentCommitment.from_redacted(
        redacted,
        secret_refs=("secret:api-key-prod",),
    )
    assert bound.commitment == commitment
    assert bound.redacted_arguments["api_key"] == "[REDACTED]"

    with pytest.raises(InvocationEnvelopeValidationError, match="commitment"):
        ArgumentCommitment(
            commitment="sha256:" + "d" * 64,
            redacted_arguments=redacted,
        )


def test_raw_secrets_rejected_in_strings_and_maps() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="raw secret"):
        _args({"token": "ghp_" + ("A" * 36)})

    with pytest.raises(InvocationEnvelopeValidationError, match="raw secret"):
        _minimal_envelope(
            purpose=PurposeContext(purpose="use key sk-proj-abcdefghijklmnopqrst"),
        )

    with pytest.raises(InvocationEnvelopeValidationError, match="redacted token"):
        _args({"password": "hunter2hunter2"})


def test_nan_and_unbounded_structures_rejected() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="NaN|non-finite|not JSON"):
        _args({"score": float("nan")})

    with pytest.raises(InvocationEnvelopeValidationError, match="NaN|infinite|non-finite"):
        _args({"score": float("inf")})

    deep: dict = {}
    cursor = deep
    for index in range(MAX_JSON_DEPTH + 5):
        cursor["child"] = {}
        cursor = cursor["child"]
    with pytest.raises(InvocationEnvelopeValidationError, match="depth"):
        _args(deep)


def test_deadline_before_created_rejected() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="deadline"):
        _minimal_envelope(
            created_at="2026-07-28T12:05:00Z",
            deadline="2026-07-28T12:00:00Z",
        )


def test_kind_mismatch_rejected() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="invocation_kind"):
        _minimal_envelope(
            invocation_kind=InvocationKind.PROMPT,
            source=SourceBinding(
                kind=InvocationKind.MCP_TOOL,
                source_ref="source:mcp-1",
            ),
        )


def test_scope_kind_mismatch_rejected() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="kind"):
        InvocationScope(
            actions=(
                ScopeEntry(
                    entry_id="scope:bad",
                    kind=ScopeKind.EFFECT,
                    value="not-an-action",
                ),
            )
        )


def test_delegation_self_link_rejected() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="must differ"):
        DelegationLink(
            link_id="del:loop",
            from_actor_id="actor:same",
            to_actor_id="actor:same",
        )


def test_source_map_bounds_and_path_rules() -> None:
    with pytest.raises(InvocationEnvelopeValidationError, match="field_path"):
        SourceMapEntry(
            map_id="map:1",
            field_path="tool.name",
            source_ref="source:x",
        )
    with pytest.raises(InvocationEnvelopeValidationError, match="start_char"):
        SourceMapEntry(
            map_id="map:2",
            field_path="/tool/tool_name",
            source_ref="source:x",
            start_char=10,
            end_char=2,
        )


def test_full_field_binding_present() -> None:
    envelope = _minimal_envelope()
    payload = envelope.to_dict()

    # Identity / source
    assert payload["schema_version"] == INVOCATION_ENVELOPE_SCHEMA_VERSION
    assert payload["source"]["kind"] == "mcp_tool"
    assert payload["source"]["source_ref"]
    assert payload["tenant_id"] == "tenant:demo"

    # Actor / delegation / audience
    assert payload["actor"]["actor_id"] == "actor:user-1"
    assert payload["delegation"][0]["from_actor_id"] == "actor:user-1"
    assert payload["audience"]["audience_id"] == "audience:dispatcher-1"

    # Tool / arguments
    assert payload["tool"]["tool_version"] == "3.1.0"
    assert payload["tool"]["server_id"] == "server:fixtures"
    assert payload["tool"]["input_schema_sha256"] == "b" * 64
    assert payload["arguments"]["commitment"].startswith("sha256:")
    assert "query" in payload["arguments"]["redacted_arguments"]

    # Scopes
    scope = payload["scope"]
    for key in (
        "actions",
        "effects",
        "capabilities",
        "resources",
        "data_classes",
        "network",
        "filesystem",
        "subprocess",
    ):
        assert scope[key], f"expected non-empty scope.{key}"

    # Purpose / environment / rollback / verification
    assert payload["purpose"]["jurisdiction"] == "US-OR"
    assert payload["environment"]["snapshot_digest"].startswith("sha256:")
    assert payload["rollback"][0]["step_id"] == "rollback:noop"
    assert payload["verification"][0]["predicate"] == "schema_valid"

    # Policy / time / maps / assumptions / diagnostics / unsupported
    assert payload["policy"]["corpus_roots"]
    assert payload["nonce"]
    assert payload["deadline"] > payload["created_at"]
    assert payload["source_maps"][0]["field_path"].startswith("/")
    assert payload["assumptions"][0]["assumption_id"]
    assert payload["diagnostics"][0]["severity"] == "info"
    assert payload["unsupported_fields"][0]["field_path"]


def test_prompt_and_skillcenter_kinds() -> None:
    skill = _minimal_envelope(
        invocation_kind=InvocationKind.SKILLCENTER,
        source=SourceBinding(
            kind=InvocationKind.SKILLCENTER,
            source_ref="source:skill-42",
            source_revision="snapshot-abc",
            content_sha256="e" * 64,
        ),
        tool=ToolBinding(tool_id="tool:skill-procedure", tool_name="skill"),
    )
    assert skill.source.kind is InvocationKind.SKILLCENTER

    prompt = _minimal_envelope(
        invocation_kind=InvocationKind.PROMPT,
        source=SourceBinding(
            kind=InvocationKind.PROMPT,
            source_ref="source:prompt-7",
            content_sha256="f" * 64,
        ),
        tool=ToolBinding(tool_id="tool:prompt-outcome", tool_name="prompt"),
    )
    assert prompt.invocation_kind is InvocationKind.PROMPT
    assert prompt.content_digest != skill.content_digest


def test_deepcopy_and_payload_isolation() -> None:
    envelope = _minimal_envelope()
    payload = envelope.to_dict()
    payload["tenant_id"] = "tenant:mutated"
    payload["arguments"]["redacted_arguments"]["query"] = "mutated"
    # Original remains intact; re-parse of original dict still matches.
    original = envelope.to_dict()
    assert original["tenant_id"] == "tenant:demo"
    assert original["arguments"]["redacted_arguments"]["query"] == "list fixtures"
    # Deep copy of to_dict is independent.
    clone = deepcopy(original)
    clone["nonce"] = "nonce:other"
    assert envelope.nonce == "nonce:01JABCDEFGHJKMNPQRSTVWXYZ0"
