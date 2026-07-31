"""Unit tests for prompt and MCP tool Intent source adapters (LIG-005)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir import (
    IntentKind,
    ReviewStatus,
    validate_intent_ir,
)
from ipfs_datasets_py.logic.intent_ir.canonicalize import (
    canonical_intent_ir_json,
    intent_ir_sha256,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.mcp_tool import (
    AllowedUseDecision as MCPAllowedUse,
    FindingDecision as MCPFindingDecision,
    MCPToolIntentAdapter,
    MCPToolPolicyError,
    MCPToolRecord,
    MCPToolRecordError,
    MCPToolSourcePolicy,
    MCP_TOOL_INTENT_ADAPTER,
    TrustDecision as MCPTrust,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.prompt import (
    AllowedUseDecision as PromptAllowedUse,
    FindingDecision as PromptFindingDecision,
    PROMPT_INTENT_ADAPTER,
    PromptIntentAdapter,
    PromptPolicyError,
    PromptRecord,
    PromptRecordError,
    PromptSourcePolicy,
    TrustDecision as PromptTrust,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterBundleReader,
    SkillCenterSkillRecord,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "intent_ir"
    / "prompt_mcp"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return _load_json(FIXTURE_ROOT / "manifest.json")


def _expected_identities() -> dict:
    return _load_json(FIXTURE_ROOT / "expected_identities.json")


def _prompt_fixture(fixture_id: str) -> dict:
    return _load_json(FIXTURE_ROOT / "prompts" / f"{fixture_id}.json")


def _mcp_fixture(fixture_id: str) -> dict:
    return _load_json(FIXTURE_ROOT / "mcp_tools" / f"{fixture_id}.json")


def _prompt_record_from_fixture(data: dict) -> PromptRecord:
    adapter = PromptIntentAdapter()
    return adapter.make_record(
        data["text"],
        title=data.get("title", ""),
        source_uri=data.get("source_uri", ""),
        source_id=data.get("source_id", ""),
        source_revision=data.get("source_revision", "unpinned"),
        language=data.get("language", "en"),
        tags=tuple(data.get("tags", ())),
        metadata=data.get("metadata"),
    )


def _mcp_record_from_fixture(data: dict) -> MCPToolRecord:
    adapter = MCPToolIntentAdapter()
    return adapter.make_record(
        data["name"],
        description=data.get("description", ""),
        input_schema=data.get("input_schema"),
        server_name=data.get("server_name", ""),
        source_uri=data.get("source_uri", ""),
        source_id=data.get("source_id", ""),
        source_revision=data.get("source_revision", "unpinned"),
        tags=tuple(data.get("tags", ())),
        annotations=data.get("annotations"),
    )


# ---------------------------------------------------------------------------
# Fixture inventory
# ---------------------------------------------------------------------------


def test_fixture_manifest_lists_benign_and_adversarial_cases() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == "prompt-mcp-fixtures/v1"
    assert manifest["interface"]["prompt"] == PROMPT_INTENT_ADAPTER
    assert manifest["interface"]["mcp_tool"] == MCP_TOOL_INTENT_ADAPTER
    assert "benign_goal" in manifest["benign_prompt_ids"]
    assert "benign_echo" in manifest["benign_mcp_tool_ids"]
    assert len(manifest["adversarial_prompt_ids"]) >= 3
    assert len(manifest["adversarial_mcp_tool_ids"]) >= 3
    for fixture_id in manifest["prompts"]:
        assert (FIXTURE_ROOT / "prompts" / f"{fixture_id}.json").is_file()
    for fixture_id in manifest["mcp_tools"]:
        assert (FIXTURE_ROOT / "mcp_tools" / f"{fixture_id}.json").is_file()


# ---------------------------------------------------------------------------
# Prompt adapter: identity stability and benign path
# ---------------------------------------------------------------------------


def test_prompt_identity_digests_are_stable_across_calls() -> None:
    data = _prompt_fixture("benign_goal")
    first = _prompt_record_from_fixture(data)
    second = _prompt_record_from_fixture(data)
    expected = _expected_identities()["prompts"]["benign_goal"]

    assert first.entry_cid == second.entry_cid == expected["entry_cid"]
    assert (
        first.entry_identity.sha256
        == second.entry_identity.sha256
        == expected["entry_sha256"]
    )
    assert first.content_sha256 == second.content_sha256 == expected["content_sha256"]
    assert first.entry_identity.cid.startswith("b")
    assert first.content_cid.startswith("b")


def test_prompt_identity_ignores_mutable_packaging_fields() -> None:
    data = _prompt_fixture("benign_goal")
    base = _prompt_record_from_fixture(data)
    repackaged = PromptIntentAdapter().make_record(
        data["text"],
        title=data["title"],
        source_uri="file:///tmp/other-path",
        source_id="different-packaging-id",
        source_revision="another-revision",
        language=data["language"],
        tags=tuple(data["tags"]),
        metadata=data["metadata"],
    )
    assert base.entry_cid == repackaged.entry_cid
    assert base.content_sha256 == repackaged.content_sha256
    assert base.to_source_ref().ref_id != repackaged.to_source_ref().ref_id


def test_benign_prompt_adapts_to_validated_intent_ir() -> None:
    data = _prompt_fixture("benign_goal")
    record = _prompt_record_from_fixture(data)
    adapter = PromptIntentAdapter()
    document, decision = adapter.adapt_with_policy(record)

    assert decision.allowed_use is PromptAllowedUse.ALLOW_INTERNAL_EVALUATION
    assert decision.trust_decision is PromptTrust.UNTRUSTED
    assert decision.hostile_input_decision is PromptFindingDecision.CLEAR
    assert decision.secret_pii_decision is PromptFindingDecision.CLEAR
    assert document.intent_kind is IntentKind.DECLARATIVE
    assert document.statements
    assert document.actions
    assert all(source.review_status is ReviewStatus.UNREVIEWED for source in document.sources)
    validated = validate_intent_ir(document)
    digest_a = intent_ir_sha256(validated)
    digest_b = intent_ir_sha256(adapter.adapt(record))
    assert digest_a == digest_b
    assert canonical_intent_ir_json(validated) == canonical_intent_ir_json(
        adapter.adapt(record)
    )


# ---------------------------------------------------------------------------
# Prompt adapter: adversarial injection fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_id",
    (
        "injection_ignore_instructions",
        "injection_tool_directive",
        "injection_secret",
    ),
)
def test_adversarial_prompt_fixtures_fail_closed(fixture_id: str) -> None:
    data = _prompt_fixture(fixture_id)
    record = _prompt_record_from_fixture(data)
    adapter = PromptIntentAdapter()
    decision = adapter.evaluate(record)
    expected = _expected_identities()["prompts"][fixture_id]

    assert decision.allowed_use is PromptAllowedUse.EXCLUDED
    assert decision.trust_decision is PromptTrust.QUARANTINED
    assert decision.review_status is ReviewStatus.QUARANTINED
    assert decision.findings
    assert record.entry_cid == expected["entry_cid"]
    assert record.entry_identity.sha256 == expected["entry_sha256"]

    with pytest.raises(PromptPolicyError) as exc_info:
        adapter.adapt(record)
    assert exc_info.value.decision.allowed_use is PromptAllowedUse.EXCLUDED


def test_prompt_injection_detector_codes_are_specific() -> None:
    ignore = PromptSourcePolicy().evaluate(
        _prompt_record_from_fixture(_prompt_fixture("injection_ignore_instructions"))
    )
    tool = PromptSourcePolicy().evaluate(
        _prompt_record_from_fixture(_prompt_fixture("injection_tool_directive"))
    )
    secret = PromptSourcePolicy().evaluate(
        _prompt_record_from_fixture(_prompt_fixture("injection_secret"))
    )

    assert any(f.code == "hostile.ignore_instructions" for f in ignore.findings)
    assert ignore.hostile_input_decision is PromptFindingDecision.QUARANTINED
    assert any(
        f.code in {"hostile.tool_call_markup", "hostile.tool_instruction"}
        for f in tool.findings
    )
    assert any(f.category.value == "secret" for f in secret.findings)
    assert secret.secret_pii_decision is PromptFindingDecision.QUARANTINED


def test_prompt_bounds_reject_oversized_text() -> None:
    adapter = PromptIntentAdapter(max_text_chars=32)
    with pytest.raises(PromptRecordError):
        adapter.make_record("x" * 33)


def test_prompt_empty_text_rejected() -> None:
    with pytest.raises(PromptRecordError):
        PromptIntentAdapter().make_record("   ")


# ---------------------------------------------------------------------------
# MCP tool adapter: identity stability and benign path
# ---------------------------------------------------------------------------


def test_mcp_tool_identity_digests_are_stable_across_calls() -> None:
    data = _mcp_fixture("benign_echo")
    first = _mcp_record_from_fixture(data)
    second = _mcp_record_from_fixture(data)
    expected = _expected_identities()["mcp_tools"]["benign_echo"]

    assert first.entry_cid == second.entry_cid == expected["entry_cid"]
    assert (
        first.entry_identity.sha256
        == second.entry_identity.sha256
        == expected["entry_sha256"]
    )
    assert first.content_sha256 == second.content_sha256 == expected["content_sha256"]


def test_mcp_tool_identity_ignores_mutable_packaging_fields() -> None:
    data = _mcp_fixture("benign_echo")
    base = _mcp_record_from_fixture(data)
    repackaged = MCPToolIntentAdapter().make_record(
        data["name"],
        description=data["description"],
        input_schema=data["input_schema"],
        server_name=data["server_name"],
        source_uri="mcp://other/path",
        source_id="packaging-other",
        source_revision="rev-other",
        tags=tuple(data["tags"]),
        annotations=data["annotations"],
    )
    assert base.entry_cid == repackaged.entry_cid
    assert base.content_sha256 == repackaged.content_sha256


def test_benign_mcp_tool_adapts_to_validated_intent_ir() -> None:
    data = _mcp_fixture("benign_echo")
    record = _mcp_record_from_fixture(data)
    adapter = MCPToolIntentAdapter()
    document, decision = adapter.adapt_with_policy(record)

    assert decision.allowed_use is MCPAllowedUse.ALLOW_INTERNAL_EVALUATION
    assert decision.trust_decision is MCPTrust.UNTRUSTED
    assert decision.hostile_input_decision is MCPFindingDecision.CLEAR
    assert document.intent_kind is IntentKind.CAPABILITY
    assert document.actions
    assert record.name in document.actions[0].tool_refs
    assert document.actions[0].verb == record.name
    assert "mcp-tool" in document.tags
    validate_intent_ir(document)
    # Re-adapt must be byte-stable.
    assert intent_ir_sha256(document) == intent_ir_sha256(adapter.adapt(record))


# ---------------------------------------------------------------------------
# MCP tool adapter: adversarial injection fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_id",
    (
        "injection_shell_tool",
        "injection_prompt_in_description",
        "injection_remote_ref",
    ),
)
def test_adversarial_mcp_tool_fixtures_fail_closed(fixture_id: str) -> None:
    data = _mcp_fixture(fixture_id)
    record = _mcp_record_from_fixture(data)
    adapter = MCPToolIntentAdapter()
    decision = adapter.evaluate(record)
    expected = _expected_identities()["mcp_tools"][fixture_id]

    assert decision.allowed_use is MCPAllowedUse.EXCLUDED
    assert decision.trust_decision is MCPTrust.QUARANTINED
    assert decision.review_status is ReviewStatus.QUARANTINED
    assert decision.findings
    assert record.entry_cid == expected["entry_cid"]

    with pytest.raises(MCPToolPolicyError) as exc_info:
        adapter.adapt(record)
    assert exc_info.value.decision.allowed_use is MCPAllowedUse.EXCLUDED


def test_mcp_remote_ref_and_shell_findings_are_specific() -> None:
    shell = MCPToolSourcePolicy().evaluate(
        _mcp_record_from_fixture(_mcp_fixture("injection_shell_tool"))
    )
    remote = MCPToolSourcePolicy().evaluate(
        _mcp_record_from_fixture(_mcp_fixture("injection_remote_ref"))
    )
    prompt = MCPToolSourcePolicy().evaluate(
        _mcp_record_from_fixture(_mcp_fixture("injection_prompt_in_description"))
    )

    assert any(f.code == "hostile.shell_tool" for f in shell.findings)
    assert any(f.code == "schema.remote_or_dynamic_ref" for f in remote.findings)
    assert any(f.code == "hostile.ignore_instructions" for f in prompt.findings)


def test_mcp_tool_malformed_name_rejected() -> None:
    with pytest.raises(MCPToolRecordError):
        MCPToolIntentAdapter().make_record("not a valid name!")


def test_mcp_tool_schema_depth_bounds() -> None:
    nested: dict = {"type": "object", "properties": {}}
    current = nested["properties"]
    for index in range(40):
        key = f"level{index}"
        current[key] = {"type": "object", "properties": {}}
        current = current[key]["properties"]
    with pytest.raises(MCPToolRecordError):
        MCPToolIntentAdapter().make_record("deep_tool", input_schema=nested)


# ---------------------------------------------------------------------------
# Non-execution and SkillCenter path unchanged
# ---------------------------------------------------------------------------


def test_adapters_do_not_execute_tool_or_prompt_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hostile content must never trigger process execution helpers."""

    def _blocked(*_args, **_kwargs):  # pragma: no cover - fail if called
        raise AssertionError("process execution must not be invoked")

    for name in (
        "os.system",
        "subprocess.Popen",
        "subprocess.run",
        "subprocess.call",
    ):
        monkeypatch.setattr(name, _blocked, raising=False)

    prompt = _prompt_record_from_fixture(_prompt_fixture("injection_tool_directive"))
    tool = _mcp_record_from_fixture(_mcp_fixture("injection_shell_tool"))
    PromptSourcePolicy().evaluate(prompt)
    MCPToolSourcePolicy().evaluate(tool)
    with pytest.raises(PromptPolicyError):
        PromptIntentAdapter().adapt(prompt)
    with pytest.raises(MCPToolPolicyError):
        MCPToolIntentAdapter().adapt(tool)


def test_skillcenter_path_unchanged_for_record_identity_and_source_ref() -> None:
    """LIG-005 must not alter SkillCenter SQLite reader identity behavior."""

    record = SkillCenterSkillRecord(
        skill_id="skill-1",
        domain="security",
        profile="security",
        source_type="github",
        source_url="https://example.test/repository/skill-1",
        title="Bounded fixture",
        overall_score=4.0,
        skill_kind="github",
        language="en",
        source_id="source-1",
        primary_source_id="primary-1",
        metadata_yaml='license_spdx: "MIT"\nlicense_risk: "allow"\n',
        skill_md="# Fixture\n\nDescribe a bounded operation.",
        library_md="",
        dataset_id="example/skillcenter",
        dataset_revision="revision-123",
        repository_file="pilot/security.sqlite",
        bundle_sha256="a" * 64,
    )
    identity_a = record.entry_identity
    identity_b = record.entry_identity
    assert identity_a.cid == identity_b.cid
    assert identity_a.sha256 == identity_b.sha256
    source = record.to_source_ref()
    source.validate()
    assert source.ref_id.startswith("skillcenter:")
    assert source.content_sha256 == record.content_sha256
    # Reader class still exposes the public contract used by pilots.
    assert hasattr(SkillCenterBundleReader, "inspect")
    assert hasattr(SkillCenterBundleReader, "iter_records")


def test_all_fixture_identities_match_frozen_expected_table() -> None:
    expected = _expected_identities()
    for fixture_id, values in expected["prompts"].items():
        record = _prompt_record_from_fixture(_prompt_fixture(fixture_id))
        decision = PromptIntentAdapter().evaluate(record)
        assert record.entry_cid == values["entry_cid"]
        assert record.entry_identity.sha256 == values["entry_sha256"]
        assert record.content_sha256 == values["content_sha256"]
        assert decision.allowed_use.value == values["allowed_use"]
    for fixture_id, values in expected["mcp_tools"].items():
        record = _mcp_record_from_fixture(_mcp_fixture(fixture_id))
        decision = MCPToolIntentAdapter().evaluate(record)
        assert record.entry_cid == values["entry_cid"]
        assert record.entry_identity.sha256 == values["entry_sha256"]
        assert record.content_sha256 == values["content_sha256"]
        assert decision.allowed_use.value == values["allowed_use"]
