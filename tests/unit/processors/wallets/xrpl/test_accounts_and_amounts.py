"""Account validation and exact amount projection tests."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    InvalidRequestError,
    NormalizationError,
)
from ipfs_datasets_py.processors.wallets.xrpl import (
    XRPLNetwork,
    exact_drops,
    exact_issued,
    parse_drops,
    parse_issued_value,
    validate_classic_address,
    xrp_asset,
    issued_asset,
    chain_ref_for,
)


ALICE = "rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz"
ISSUER = "r3bmF74WayREhyVYaqbu7GqLKvqZvUF3k6"


def test_classic_address_checksum() -> None:
    desc = validate_classic_address(ALICE, network=XRPLNetwork.MAINNET)
    assert desc.address == ALICE
    assert desc.account_id_hex is not None
    assert len(desc.account_id_hex) == 40


def test_x_address_rejected() -> None:
    with pytest.raises(NormalizationError, match="X-address"):
        validate_classic_address(
            "XV5sbjUmgPpvXv4ixFWZ5ptAYZ6PD28Sq49uo34VyjnmK5H",
            network=XRPLNetwork.MAINNET,
        )


def test_invalid_checksum_rejected() -> None:
    bad = ALICE[:-1] + ("z" if ALICE[-1] != "z" else "y")
    with pytest.raises(NormalizationError, match="checksum"):
        validate_classic_address(bad, network=XRPLNetwork.MAINNET)


def test_parse_drops_rejects_float() -> None:
    with pytest.raises(InvalidRequestError):
        parse_drops(1.5)
    assert parse_drops("1000000") == 1_000_000
    assert exact_drops(12).base_units == "12"
    assert exact_drops(12).decimals == 6


def test_issued_value_scale() -> None:
    base, decimals = parse_issued_value("25.50")
    assert base == 2550
    assert decimals == 2
    amount = exact_issued("25.50")
    assert amount.base_units == "2550"
    assert amount.decimals == 2


def test_issued_asset_requires_currency_and_issuer() -> None:
    chain = chain_ref_for(XRPLNetwork.MAINNET)
    asset = issued_asset(chain, currency="USD", issuer=ISSUER, decimals=2)
    assert asset.asset_namespace == "xrpl-token"
    assert ISSUER in asset.asset_reference
    assert "USD" in asset.asset_reference
    native = xrp_asset(chain)
    assert native.kind.value == "native"
    assert native.decimals == 6
