"""LCR-073 no-mutate Federal Register prepublication seal tests."""

from __future__ import annotations

import pytest

import scripts.ops.legal_data.seal_federal_register_prepublication as seal


def test_missing_no_mutate_fails_closed() -> None:
    with pytest.raises(seal.PrepublicationSealError, match="no-mutate"):
        seal.inspect_federal_prepublication_seal(
            require_live_staging_pin=True,
            no_mutate=False,
        )


def test_missing_live_staging_pin_fails_closed() -> None:
    with pytest.raises(seal.PrepublicationSealError, match="staging"):
        seal.inspect_federal_prepublication_seal(
            require_live_staging_pin=True,
            no_mutate=True,
        )


def test_cli_require_live_staging_exits_nonzero() -> None:
    assert (
        seal.main(["--require-live-staging-pin", "--no-mutate", "--check"]) == 1
    )
