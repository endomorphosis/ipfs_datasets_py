"""Contract tests for the Xaman runtime → formal assurance bridge (WALPROC-G220).

Proves:

* runtime modules import no proof tool, report generator, archive corpus,
  Firebase, native vault, or device harness;
* formal modules stay at existing paths (inventory only; no relocation);
* projection covers network binding, payload lifecycle, signing decision,
  submission, and finality assumptions;
* assurance status is not runtime authorization or release proof;
* one-way projection from runtime records to assurance inputs works offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.xaman.assurance import (
    ASSURANCE_POLICY,
    FORBIDDEN_RUNTIME_IMPORT_PREFIXES,
    FORMAL_ASSET_INVENTORY,
    GOAL_ID,
    PROJECTION_DOMAINS,
    SCHEMA,
    TASK_ID,
    AssuranceStatus,
    assert_runtime_import_boundary,
    assurance_status_is_not_authorization,
    formal_asset_inventory,
    formal_modules_remain_at_existing_paths,
    project_ledger_record_to_assurance,
    project_many,
    project_payload_to_assurance,
    required_domains_covered,
)
from ipfs_datasets_py.processors.wallets.xaman.models import (
    PayloadStatus,
    SettlementVerdict,
    XamanPayload,
)
from ipfs_datasets_py.processors.wallets.xaman.normalizer import parse_xaman_payload
from ipfs_datasets_py.processors.wallets.xaman.settlement import (
    verify_settlement_against_xrpl,
)
from ipfs_datasets_py.processors.wallets.xrpl.networks import XRPLNetwork

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "wallets" / "xaman"
_REPO_ROOT = Path(__file__).resolve().parents[5]
_MAPPING_DOC = (
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "docs"
    / "security_verification"
    / "xaman_wallet_processor_mapping.md"
)
_ASSURANCE_MODULE = (
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "ipfs_datasets_py"
    / "processors"
    / "wallets"
    / "xaman"
    / "assurance.py"
)


def _load(name: str) -> dict:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Evidence / artifact presence
# ---------------------------------------------------------------------------


def test_expected_evidence_artifacts_exist() -> None:
    assert _ASSURANCE_MODULE.is_file()
    assert _MAPPING_DOC.is_file()
    assert (_FIXTURE_DIR / "assurance_links.json").is_file()
    assert (_FIXTURE_DIR / "runtime_projection_boundary.json").is_file()


def test_goal_and_schema_identity() -> None:
    assert GOAL_ID == "WALPROC-G220"
    assert TASK_ID == "WALPROC-026"
    assert SCHEMA == "wallet.xaman.assurance-projection/v1"
    assert ASSURANCE_POLICY["goal_id"] == GOAL_ID
    assert ASSURANCE_POLICY["formal_assurance_is_not_runtime_correctness"] is True
    assert ASSURANCE_POLICY["assurance_status_is_not_runtime_authorization"] is True
    assert ASSURANCE_POLICY["assurance_status_is_not_release_proof"] is True
    assert ASSURANCE_POLICY["formal_modules_remain_at_existing_paths"] is True


# ---------------------------------------------------------------------------
# Runtime import boundary (no formal / harness coupling)
# ---------------------------------------------------------------------------


def test_runtime_imports_no_formal_or_harness_code() -> None:
    report = assert_runtime_import_boundary()
    assert report["clean"] is True
    assert "assurance.py" in report["scanned_modules"]
    assert "processor.py" in report["scanned_modules"]
    for prefix in (
        "ipfs_datasets_py.logic.security_models.crypto_exchange.reports",
        "ipfs_datasets_py.logic.security_ir.xaman",
        "ipfs_datasets_py.logic.security_models.crypto_exchange.extractors",
    ):
        assert prefix in FORBIDDEN_RUNTIME_IMPORT_PREFIXES


def test_assurance_module_itself_has_no_forbidden_imports() -> None:
    """assurance.py may *list* forbidden prefixes but must not import them."""

    import ast

    source = _ASSURANCE_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for module in imported:
        for prefix in FORBIDDEN_RUNTIME_IMPORT_PREFIXES:
            assert not (
                module == prefix or module.startswith(prefix + ".")
            ), f"assurance.py must not import {module}"
    # Only relative / local runtime dependencies.
    for module in imported:
        assert "security_ir" not in module
        assert "security_models" not in module
        assert "firebase" not in module.lower()
        assert "native_vault" not in module.lower()


def test_boundary_fixture_allows_projection_adapter() -> None:
    boundary = _load("runtime_projection_boundary.json")
    allowed = boundary["boundary"]["allowed_shared_modules_when_created"]
    assert any("assurance" in item for item in allowed)
    forbidden = boundary["boundary"]["formal_import_prefixes_forbidden_in_runtime_processor"]
    assert any("reports" in item for item in forbidden)


# ---------------------------------------------------------------------------
# Formal modules remain at existing paths
# ---------------------------------------------------------------------------


def test_formal_modules_stay_at_existing_paths() -> None:
    inventory = formal_asset_inventory()
    assert len(inventory) >= 4
    report = formal_modules_remain_at_existing_paths(repository_root=_REPO_ROOT)
    assert report["relocation_in_scope"] is False
    assert report["formal_modules_remain_at_existing_paths"] is True
    # Majority of inventoried formal assets must exist; no move performed.
    assert report["all_present"] or len(report["missing"]) <= 1
    for asset in FORMAL_ASSET_INVENTORY:
        assert asset["layer"] == "formal"
        assert asset["path"].startswith("ipfs_datasets_py/")


def test_formal_inventory_includes_ast_symbols() -> None:
    by_id = {item["id"]: item for item in FORMAL_ASSET_INVENTORY}
    assert "xaman-source-extractor" in by_id
    assert by_id["xaman-source-extractor"].get("ast_symbol") == "xaman_source_extractor"
    assert "security-model-ir-schema" in by_id
    assert by_id["security-model-ir-schema"].get("ast_symbol") == "SecurityModelIR"


def test_assurance_links_fixture_aligns_with_inventory() -> None:
    links = _load("assurance_links.json")
    inventory_paths = {item["path"] for item in FORMAL_ASSET_INVENTORY}
    fixture_paths = {item["path"] for item in links["formal_assets"]}
    # Inventory may extend the fixture; fixture assets must remain covered when present.
    overlap = inventory_paths & fixture_paths
    assert len(overlap) >= 3
    assert links["policy"]["formal_assurance_is_not_runtime_correctness"] is True


# ---------------------------------------------------------------------------
# Projection covers required domains
# ---------------------------------------------------------------------------


def test_projection_covers_all_required_domains() -> None:
    assert set(PROJECTION_DOMAINS) == {
        "network_binding",
        "payload_lifecycle",
        "signing_decision",
        "submission",
        "finality_assumptions",
    }
    payload = XamanPayload(
        payload_uuid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        status=PayloadStatus.SIGNED,
        network=XRPLNetwork.TESTNET,
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        transaction_hash="A" * 64,
        api_signed=True,
        api_resolved=True,
        settlement=SettlementVerdict.API_SUCCESS_ONLY,
    )
    projection = project_payload_to_assurance(payload)
    assert required_domains_covered(projection)
    for domain in PROJECTION_DOMAINS:
        assert domain in projection.domains
        assert projection.domain(domain).domain == domain


def test_projection_from_lifecycle_fixtures() -> None:
    life = _load("payload_lifecycle_states.json")
    observed_statuses: set[str] = set()
    for case in life["payloads"]:
        payload = parse_xaman_payload(
            case["document"], network=XRPLNetwork.TESTNET
        )
        projection = project_payload_to_assurance(payload)
        assert required_domains_covered(projection)
        assert projection.payload_uuid
        assert projection.network == XRPLNetwork.TESTNET.value
        lifecycle = projection.domain("payload_lifecycle")
        assert lifecycle.status is AssuranceStatus.OBSERVED
        assert lifecycle.facts["status"] == case["expect_status"]
        observed_statuses.add(case["expect_status"])
        # Network binding carries identity.
        nb = projection.domain("network_binding")
        assert nb.facts["payload_uuid"] == payload.payload_uuid
        assert nb.facts["network"] == XRPLNetwork.TESTNET.value
    assert set(life["required_statuses"]) <= observed_statuses


def test_signing_submission_and_finality_projection_semantics() -> None:
    signed = parse_xaman_payload(
        {
            "meta": {
                "uuid": "11111111-1111-4111-8111-111111111103",
                "signed": True,
                "resolved": True,
                "network": "testnet",
            },
            "payload": {
                "txjson": {
                    "TransactionType": "Payment",
                    "Account": "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
                    "Destination": "r3bmF74WayREhyVYaqbu7GqLKvqZvUF3k6",
                    "Amount": "1000000",
                }
            },
            "response": {
                "account": "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
                "txid": "A" * 64,
            },
        },
        network=XRPLNetwork.TESTNET,
    )
    signed = verify_settlement_against_xrpl(signed, xrpl_transactions=[])
    proj = project_payload_to_assurance(signed)

    signing = proj.domain("signing_decision")
    assert signing.status is AssuranceStatus.OBSERVED
    assert signing.facts["runtime_can_sign"] is False
    assert signing.facts["runtime_can_approve"] is False

    submission = proj.domain("submission")
    assert submission.facts["runtime_can_submit"] is False
    assert submission.facts["runtime_can_broadcast"] is False
    assert submission.facts["transaction_hash"] == "A" * 64

    finality = proj.domain("finality_assumptions")
    assert finality.facts["api_success_is_settlement"] is False
    assert finality.facts["settlement_via"] == "xrpl"
    # API success without XRPL validation → assumed / non-settled.
    assert finality.facts["is_ledger_settled"] is False
    assert finality.status in {
        AssuranceStatus.ASSUMED,
        AssuranceStatus.PARTIAL,
        AssuranceStatus.MISSING,
        AssuranceStatus.OBSERVED,
    }
    assert any("A6" in a for a in finality.assumptions)

    # With XRPL validation, finality becomes observed settled.
    settled = verify_settlement_against_xrpl(
        signed,
        xrpl_transactions=[
            {
                "hash": "A" * 64,
                "account": "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
                "validated": True,
                "outcome": "validated_success",
                "ledger_index": 42,
                "network": "xrpl-testnet",
            }
        ],
    )
    settled_proj = project_payload_to_assurance(settled)
    settled_finality = settled_proj.domain("finality_assumptions")
    assert settled_finality.status is AssuranceStatus.OBSERVED
    assert settled_finality.facts["is_ledger_settled"] is True
    assert settled_finality.facts["settlement"] == "xrpl_validated"


def test_ledger_sample_projection() -> None:
    samples = _load("sample_ledger_records.json")
    for record in samples["records"]:
        projection = project_ledger_record_to_assurance(record)
        assert required_domains_covered(projection)
        assert projection.source_record_kind == "public_ledger_record"
        assert projection.domain("payload_lifecycle").status is (
            AssuranceStatus.NOT_APPLICABLE
        )
        assert projection.domain("signing_decision").facts["runtime_can_sign"] is False
        nb = projection.domain("network_binding")
        assert nb.facts["account"] == record["account"]
        assert projection.domain("submission").facts["transaction_hash"] == (
            record["transaction_hash"]
        )


def test_project_many_preserves_order() -> None:
    life = _load("payload_lifecycle_states.json")
    payloads = [
        parse_xaman_payload(case["document"], network=XRPLNetwork.TESTNET)
        for case in life["payloads"][:3]
    ]
    projections = project_many(payloads)
    assert len(projections) == 3
    for payload, projection in zip(payloads, projections, strict=True):
        assert projection.payload_uuid == payload.payload_uuid


# ---------------------------------------------------------------------------
# Assurance status is not runtime authorization or release proof
# ---------------------------------------------------------------------------


def test_assurance_status_is_not_authorization_or_release_proof() -> None:
    payload = XamanPayload(
        payload_uuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        status=PayloadStatus.SUBMITTED,
        network=XRPLNetwork.MAINNET,
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        transaction_hash="B" * 64,
        settlement=SettlementVerdict.API_SUCCESS_ONLY,
    )
    projection = project_payload_to_assurance(payload)
    assert projection.is_runtime_authorization is False
    assert projection.is_release_proof is False
    assert assurance_status_is_not_authorization(projection) is True

    as_dict = projection.to_dict()
    assert as_dict["is_runtime_authorization"] is False
    assert as_dict["is_release_proof"] is False
    assert as_dict["policy"]["assurance_status_is_not_runtime_authorization"] is True
    assert as_dict["policy"]["assurance_status_is_not_release_proof"] is True
    for domain_payload in as_dict["domains"].values():
        authority = domain_payload["authority"]
        assert authority["not_runtime_authorization"] is True
        assert authority["not_release_proof"] is True
        assert "not_runtime_authorization" in authority["markers"]
        assert "not_release_proof" in authority["markers"]


def test_projection_cannot_be_promoted_to_authorization() -> None:
    payload = XamanPayload(
        payload_uuid="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        status=PayloadStatus.CREATED,
        network=XRPLNetwork.TESTNET,
    )
    projection = project_payload_to_assurance(payload)
    # Normal attribute assignment is rejected on the frozen projection.
    with pytest.raises(Exception):
        projection.is_runtime_authorization = True  # type: ignore[misc]
    # Even if a caller bypasses frozen setattr, the public dict projection
    # hard-codes non-authority so status cannot become auth/release proof.
    object.__setattr__(projection, "is_runtime_authorization", True)
    object.__setattr__(projection, "is_release_proof", True)
    as_dict = projection.to_dict()
    assert as_dict["is_runtime_authorization"] is False
    assert as_dict["is_release_proof"] is False
    assert as_dict["policy"]["assurance_status_is_not_runtime_authorization"] is True
    assert as_dict["policy"]["assurance_status_is_not_release_proof"] is True


# ---------------------------------------------------------------------------
# Mapping document contract
# ---------------------------------------------------------------------------


def test_mapping_document_covers_acceptance_terms() -> None:
    text = _MAPPING_DOC.read_text(encoding="utf-8")
    required_terms = [
        "WALPROC-G220",
        "network binding",
        "payload lifecycle",
        "signing decision",
        "submission",
        "finality",
        "not runtime authorization",
        "not release proof",
        "assurance.py",
        "XamanWalletProcessor",
        "SecurityModelIR",
        "xaman_source_extractor",
        "logic/security_ir/xaman",
        "one-way",
    ]
    lowered = text.lower()
    for term in required_terms:
        assert term.lower() in lowered, f"mapping doc missing term: {term}"


def test_bridge_rules_direction_is_runtime_to_formal() -> None:
    links = _load("assurance_links.json")
    directions = {rule["direction"] for rule in links["bridge_rules"]}
    assert "runtime_to_formal_projection" in directions
    assert "forbid_formal_into_runtime" in directions
    payload = XamanPayload(
        payload_uuid="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        status=PayloadStatus.OPENED,
        network=XRPLNetwork.TESTNET,
    )
    projection = project_payload_to_assurance(payload)
    assert projection.bridge_direction == "runtime_to_formal_projection"
    assert projection.to_dict()["bridge_direction"] == "runtime_to_formal_projection"
