"""EAAEF-072: all plan obligations must hold; no self-granted authority."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.external_work_plan_obligations import (
    KINDS,
    ObligationError,
    prove,
)


def _all_hold():
    return [{"kind": kind, "holds": True} for kind in sorted(KINDS)]


def test_all_obligations_required() -> None:
    proved = prove(_all_hold())
    assert {item.kind for item in proved} == set(KINDS)


def test_missing_and_failed_obligations() -> None:
    with pytest.raises(ObligationError, match="missing"):
        prove([{"kind": "child_covers_parent", "holds": True}])
    with pytest.raises(ObligationError, match="do not all hold"):
        payload = _all_hold()
        payload[0]["holds"] = False
        if payload[0]["kind"] == "no_self_granted_authority":
            payload[1]["holds"] = False
            payload[0]["holds"] = True
        prove(payload)
    with pytest.raises(ObligationError, match="self-granted"):
        prove(
            [
                {"kind": kind, "holds": kind != "no_self_granted_authority"}
                for kind in sorted(KINDS)
            ]
        )
