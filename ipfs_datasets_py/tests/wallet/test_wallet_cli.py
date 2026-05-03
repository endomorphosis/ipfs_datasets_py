from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.wallet.cli import main
from ipfs_datasets_py.wallet.crypto import random_key
from ipfs_datasets_py.wallet.ucan import resource_for_record


def test_wallet_cli_local_vertical_slice(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    source = tmp_path / "source.txt"
    decrypted = tmp_path / "decrypted.txt"
    source.write_text("housing eligibility letter", encoding="utf-8")
    owner_key = random_key().hex()
    delegate_key = random_key().hex()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "create",
        "--owner-did",
        "did:key:owner",
    ]) == 0
    created = json.loads(capsys.readouterr().out)
    wallet_id = created["wallet_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "add",
        "--wallet-id",
        wallet_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--path",
        str(source),
        "--title",
        "Housing letter",
    ]) == 0
    added = json.loads(capsys.readouterr().out)
    document_id = added["document_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "grant",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--issuer-did",
        "did:key:owner",
        "--audience-did",
        "did:key:delegate",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--ability",
        "record/analyze",
        "--output-type",
        "summary",
        "--purpose",
        "analyze",
    ]) == 0
    grant = json.loads(capsys.readouterr().out)
    grant_id = grant["grant_id"]
    assert grant_id.startswith("grant-")

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "analyze",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--grant-id",
        grant_id,
    ]) == 0
    analysis = json.loads(capsys.readouterr().out)
    assert analysis["artifact_type"] == "summary"
    assert analysis["output_policy"] == "derived_only"

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "issue-invocation",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--grant-id",
        grant_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--ability",
        "record/analyze",
        "--caveat",
        "purpose=service_matching",
    ]) == 0
    invocation = json.loads(capsys.readouterr().out)
    assert invocation["invocation_token"].startswith("wallet-ucan-v1.")

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "analyze-invocation",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--invocation-token",
        invocation["invocation_token"],
    ]) == 0
    invocation_analysis = json.loads(capsys.readouterr().out)
    assert invocation_analysis["artifact_type"] == "summary"

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "decrypt",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--out",
        str(decrypted),
    ]) == 0
    assert decrypted.read_text(encoding="utf-8") == "housing eligibility letter"

    manifest_bytes = next(wallet_dir.glob("wallet-*.json")).read_bytes()
    blob_bytes = b"".join(path.read_bytes() for path in blob_dir.glob("*.bin"))
    assert b"housing eligibility letter" not in manifest_bytes
    assert b"housing eligibility letter" not in blob_bytes


def test_wallet_cli_threshold_approval_for_decrypt_grant(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    source = tmp_path / "source.txt"
    source.write_text("sensitive identity document", encoding="utf-8")
    owner_key = random_key().hex()
    delegate_key = random_key().hex()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "create",
        "--owner-did",
        "did:key:owner",
        "--controller-did",
        "did:key:second-controller",
        "--approval-threshold",
        "2",
    ]) == 0
    wallet_id = json.loads(capsys.readouterr().out)["wallet_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "add",
        "--wallet-id",
        wallet_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--path",
        str(source),
    ]) == 0
    document_id = json.loads(capsys.readouterr().out)["document_id"]
    resource = resource_for_record(wallet_id, document_id)

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "grant",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--issuer-did",
        "did:key:owner",
        "--audience-did",
        "did:key:delegate",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--ability",
        "record/decrypt",
        "--purpose",
        "decrypt",
    ]) == 1
    assert "approval_id is required" in json.loads(capsys.readouterr().out)["error"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "request-approval",
        "--wallet-id",
        wallet_id,
        "--requested-by",
        "did:key:owner",
        "--resource",
        resource,
        "--ability",
        "record/decrypt",
    ]) == 0
    approval_id = json.loads(capsys.readouterr().out)["approval_id"]

    for approver in ["did:key:owner", "did:key:second-controller"]:
        assert main([
            "--json",
            "--wallet-dir",
            str(wallet_dir),
            "--blob-dir",
            str(blob_dir),
            "approve-approval",
            "--wallet-id",
            wallet_id,
            "--approval-id",
            approval_id,
            "--approver-did",
            approver,
        ]) == 0
        approval_status = json.loads(capsys.readouterr().out)["approval_status"]
    assert approval_status == "approved"

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "grant",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--issuer-did",
        "did:key:owner",
        "--audience-did",
        "did:key:delegate",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--ability",
        "record/decrypt",
        "--purpose",
        "decrypt",
        "--approval-ref",
        approval_id,
    ]) == 0
    grant_id = json.loads(capsys.readouterr().out)["grant_id"]
    assert grant_id.startswith("grant-")

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "issue-invocation",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--grant-id",
        grant_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--ability",
        "record/decrypt",
    ]) == 0
    invocation = json.loads(capsys.readouterr().out)
    decrypted = tmp_path / "delegate-decrypted.txt"
    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "decrypt-invocation",
        "--wallet-id",
        wallet_id,
        "--document-id",
        document_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--invocation-token",
        invocation["invocation_token"],
        "--out",
        str(decrypted),
    ]) == 0
    assert decrypted.read_text(encoding="utf-8") == "sensitive identity document"


def test_wallet_cli_storage_verify_and_repair(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    source = tmp_path / "source.txt"
    source.write_text("storage health document", encoding="utf-8")
    owner_key = random_key().hex()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "create",
        "--owner-did",
        "did:key:owner",
    ]) == 0
    wallet_id = json.loads(capsys.readouterr().out)["wallet_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "add",
        "--wallet-id",
        wallet_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--path",
        str(source),
    ]) == 0
    record_id = json.loads(capsys.readouterr().out)["record_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "verify-storage",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
    ]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["ok"] is True
    assert verified["payload"][0]["role"] == "primary"

    payload_ref = verified["payload"][0]
    Path(payload_ref["uri"].removeprefix("local://")).unlink()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "verify-storage",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--skip-metadata",
    ]) == 0
    broken = json.loads(capsys.readouterr().out)
    assert broken["ok"] is False
    assert broken["payload"][0]["ok"] is False

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "repair-storage",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--actor-did",
        "did:key:owner",
        "--skip-metadata",
    ]) == 0
    repair = json.loads(capsys.readouterr().out)
    assert repair["ok"] is False
    assert repair["repaired"] is False
    assert repair["payload"][0]["ok"] is False


def test_wallet_cli_share_issues_analysis_invocation(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    source = tmp_path / "source.txt"
    source.write_text("share command analysis text", encoding="utf-8")
    owner_key = random_key().hex()
    delegate_key = random_key().hex()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "create",
        "--owner-did",
        "did:key:owner",
    ]) == 0
    wallet_id = json.loads(capsys.readouterr().out)["wallet_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "add",
        "--wallet-id",
        wallet_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--path",
        str(source),
    ]) == 0
    record_id = json.loads(capsys.readouterr().out)["record_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "share",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--issuer-did",
        "did:key:owner",
        "--audience-did",
        "did:key:delegate",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--can",
        "record/analyze",
        "--output-type",
        "summary",
        "--issue-invocation",
    ]) == 0
    share = json.loads(capsys.readouterr().out)
    assert share["grant_id"].startswith("grant-")
    assert share["invocation_token"].startswith("wallet-ucan-v1.")

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "analyze-invocation",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--invocation-token",
        share["invocation_token"],
    ]) == 0
    analysis = json.loads(capsys.readouterr().out)
    assert analysis["artifact_type"] == "summary"


def test_wallet_cli_share_decrypt_respects_threshold_approval(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    source = tmp_path / "source.txt"
    source.write_text("share command decrypt text", encoding="utf-8")
    owner_key = random_key().hex()
    delegate_key = random_key().hex()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "create",
        "--owner-did",
        "did:key:owner",
        "--controller-did",
        "did:key:second-controller",
        "--approval-threshold",
        "2",
    ]) == 0
    wallet_id = json.loads(capsys.readouterr().out)["wallet_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "add",
        "--wallet-id",
        wallet_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--path",
        str(source),
    ]) == 0
    record_id = json.loads(capsys.readouterr().out)["record_id"]
    resource = resource_for_record(wallet_id, record_id)

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "share",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--issuer-did",
        "did:key:owner",
        "--audience-did",
        "did:key:delegate",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--can",
        "record/decrypt",
    ]) == 1
    assert "approval_id is required" in json.loads(capsys.readouterr().out)["error"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "request-approval",
        "--wallet-id",
        wallet_id,
        "--requested-by",
        "did:key:owner",
        "--resource",
        resource,
        "--ability",
        "record/decrypt",
    ]) == 0
    approval_id = json.loads(capsys.readouterr().out)["approval_id"]
    for approver in ["did:key:owner", "did:key:second-controller"]:
        assert main([
            "--json",
            "--wallet-dir",
            str(wallet_dir),
            "--blob-dir",
            str(blob_dir),
            "approve-approval",
            "--wallet-id",
            wallet_id,
            "--approval-id",
            approval_id,
            "--approver-did",
            approver,
        ]) == 0
        capsys.readouterr()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "share",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--issuer-did",
        "did:key:owner",
        "--audience-did",
        "did:key:delegate",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--can",
        "record/decrypt",
        "--approval-ref",
        approval_id,
        "--issue-invocation",
    ]) == 0
    share = json.loads(capsys.readouterr().out)
    decrypted = tmp_path / "share-decrypt.txt"
    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "decrypt-invocation",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--invocation-token",
        share["invocation_token"],
        "--out",
        str(decrypted),
    ]) == 0
    assert decrypted.read_text(encoding="utf-8") == "share command decrypt text"


def test_wallet_cli_access_request_approval_issues_invocation(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    source = tmp_path / "source.txt"
    source.write_text("access request command analysis text", encoding="utf-8")
    owner_key = random_key().hex()
    delegate_key = random_key().hex()

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "create",
        "--owner-did",
        "did:key:owner",
    ]) == 0
    wallet_id = json.loads(capsys.readouterr().out)["wallet_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "add",
        "--wallet-id",
        wallet_id,
        "--actor-did",
        "did:key:owner",
        "--key-hex",
        owner_key,
        "--path",
        str(source),
    ]) == 0
    record_id = json.loads(capsys.readouterr().out)["record_id"]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "request-access",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--requester-did",
        "did:key:delegate",
        "--ability",
        "record/analyze",
        "--purpose",
        "benefits_screening",
    ]) == 0
    access_request = json.loads(capsys.readouterr().out)
    assert access_request["request_id"].startswith("access-")
    assert access_request["status"] == "pending"

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "access-requests",
        "--wallet-id",
        wallet_id,
    ]) == 0
    inbox = json.loads(capsys.readouterr().out)
    assert [request["request_id"] for request in inbox["requests"]] == [access_request["request_id"]]

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "approve-access",
        "--wallet-id",
        wallet_id,
        "--request-id",
        access_request["request_id"],
        "--actor-did",
        "did:key:owner",
        "--issuer-key-hex",
        owner_key,
        "--recipient-key-hex",
        delegate_key,
        "--issue-invocation",
    ]) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["status"] == "approved"
    assert approved["grant_id"].startswith("grant-")
    assert approved["invocation_token"].startswith("wallet-ucan-v1.")

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "analyze-invocation",
        "--wallet-id",
        wallet_id,
        "--record-id",
        record_id,
        "--actor-did",
        "did:key:delegate",
        "--key-hex",
        delegate_key,
        "--invocation-token",
        approved["invocation_token"],
    ]) == 0
    analysis = json.loads(capsys.readouterr().out)
    assert analysis["artifact_type"] == "summary"


def test_wallet_cli_private_analytics_template_flow(tmp_path, capsys) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"

    wallet_ids = []
    for owner in ["did:key:owner1", "did:key:owner2"]:
        assert main([
            "--json",
            "--wallet-dir",
            str(wallet_dir),
            "--blob-dir",
            str(blob_dir),
            "create",
            "--owner-did",
            owner,
        ]) == 0
        wallet_ids.append(json.loads(capsys.readouterr().out)["wallet_id"])

    template_id = "cli_housing_gap_v1"
    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "analytics-template",
        "--wallet-id",
        wallet_ids[0],
        "--template-id",
        template_id,
        "--title",
        "Housing gaps",
        "--purpose",
        "County-level housing planning",
        "--record-type",
        "location",
        "--record-type",
        "need",
        "--derived-field",
        "county",
        "--derived-field",
        "need_category",
        "--min-cohort-size",
        "2",
        "--epsilon-budget",
        "0.5",
        "--created-by",
        "did:key:analyst",
    ]) == 0
    template = json.loads(capsys.readouterr().out)
    assert template["template_id"] == template_id

    consent_ids = []
    for wallet_id, owner in zip(wallet_ids, ["did:key:owner1", "did:key:owner2"]):
        assert main([
            "--json",
            "--wallet-dir",
            str(wallet_dir),
            "--blob-dir",
            str(blob_dir),
            "analytics-consent",
            "--wallet-id",
            wallet_id,
            "--actor-did",
            owner,
            "--template-id",
            template_id,
        ]) == 0
        consent_ids.append(json.loads(capsys.readouterr().out)["consent_id"])

    for wallet_id, owner, consent_id in zip(wallet_ids, ["did:key:owner1", "did:key:owner2"], consent_ids):
        assert main([
            "--json",
            "--wallet-dir",
            str(wallet_dir),
            "--blob-dir",
            str(blob_dir),
            "analytics-contribute",
            "--wallet-id",
            wallet_id,
            "--actor-did",
            owner,
            "--consent-id",
            consent_id,
            "--template-id",
            template_id,
            "--field",
            "county=Multnomah",
            "--field",
            "need_category=housing",
        ]) == 0
        contribution = json.loads(capsys.readouterr().out)
        assert contribution["template_id"] == template_id

    assert main([
        "--json",
        "--wallet-dir",
        str(wallet_dir),
        "--blob-dir",
        str(blob_dir),
        "analytics-count",
        "--wallet-id",
        wallet_ids[0],
        "--template-id",
        template_id,
        "--epsilon",
        "0.25",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["released"] is True
    assert result["count"] is None
    assert result["noisy_count"] is not None
    assert result["privacy_budget_spent"] == 0.25

    for wallet_id in wallet_ids:
        assert main([
            "--json",
            "--wallet-dir",
            str(wallet_dir),
            "--blob-dir",
            str(blob_dir),
            "audit",
            "--wallet-id",
            wallet_id,
        ]) == 0
        audit = json.loads(capsys.readouterr().out)
        assert audit["event_count"] >= 3
