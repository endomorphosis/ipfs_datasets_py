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
    assert json.loads(capsys.readouterr().out)["grant_id"].startswith("grant-")
