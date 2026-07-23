from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "external" / "ipfs_datasets"))

from ipfs_datasets_py.mcp_server.mcplusplus.profile_h import (  # noqa: E402
    DatasetPaymentConfig,
    DatasetPolicy,
    PaidDatasetService,
)
from mcplusplus_profile_h import CallbackFacilitator, SettlementResult, VerificationResult  # noqa: E402
from mcplusplus_profile_h.canonical import cid_for  # noqa: E402


@pytest.fixture
def calls():
    return {"verify": 0, "settle": 0}


@pytest.fixture
def facilitator(calls):
    def verify(_payload, _requirement):
        calls["verify"] += 1
        return VerificationResult(True, "H_PAYMENT_VERIFIED", verifier_did="did:web:facilitator.test")

    def settle(_payload, requirement):
        calls["settle"] += 1
        return SettlementResult(True, requirement.network, "0xtest-transaction")

    return CallbackFacilitator(verify, settle)


@pytest.fixture
def config():
    return DatasetPaymentConfig(
        seller_did="did:web:datasets.test",
        descriptor_cid=cid_for({"datasets": "descriptor"}),
        pay_to="0x1111111111111111111111111111111111111111",
        asset="0x0000000000000000000000000000000000000001",
        catalog_version="2026-07-12",
        datasets={
            "medical-v3": DatasetPolicy(
                dataset_id="medical-records", version="3", amount="75",
                license_id="research-only-v2", tenants=("clinic-a",),
                allowed_fields=("diagnosis", "age_band"), denied_fields=("patient_name",),
                row_constraints={"region": ("us-west",)}, privacy_modes=("aggregate", "dp"),
                max_rows=100, max_epsilon=1.0, minimum_k=5,
            ),
            "medical-v4": DatasetPolicy(
                dataset_id="medical-records", version="4", amount="90",
                license_id="research-only-v2", tenants=("clinic-a",),
                allowed_fields=("diagnosis",), row_constraints={"region": ("us-west",)},
                privacy_modes=("aggregate",), max_rows=50, minimum_k=5,
            ),
        },
    )


@pytest.fixture
def service(tmp_path, config, facilitator):
    return PaidDatasetService(config, tmp_path / "profile-h", facilitator)


@pytest.fixture
def request_context():
    from mcplusplus_profile_h import RequestContext

    return RequestContext(
        cid_for({"request": "dataset-1"}), "dataset-1",
        attributes={"subject": "researcher-1", "tenant": "clinic-a", "licenses": ("research-only-v2",)},
    )

